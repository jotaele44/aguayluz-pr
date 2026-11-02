"""Generic immutable manifestation and runtime-receipt store for Source Intelligence."""
from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from aguayluz import DATA_DIR
from aguayluz.hazard_plane import Manifestation

from .adapters.base import RawArtifact
from .models import SourceAttemptState, SourceRuntimeReceipt
from .runtime import persist_source_manifestation

RECEIPTS_SCHEMA = "aguayluz.source-intelligence-receipts/v1"


@dataclass(frozen=True)
class SourceIntelligencePaths:
    data_dir: Path

    @property
    def manifestations(self) -> Path:
        return self.data_dir / "source_intelligence_manifestations.jsonl"

    @property
    def receipts(self) -> Path:
        return self.data_dir / "source_intelligence_receipts.json"

    @property
    def runtime_root(self) -> Path:
        return self.data_dir / "source_intelligence"

    def snapshot_dir(self, source_family_id: str) -> Path:
        """Legacy compatibility path; canonical raw bytes live under runtime_root."""
        return self.data_dir / "source_intelligence_snapshots" / source_family_id


def source_intelligence_paths(data_dir: Path | str | None = None) -> SourceIntelligencePaths:
    return SourceIntelligencePaths(Path(data_dir) if data_dir is not None else DATA_DIR)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if path.exists():
            os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def freeze_artifact(\n    source_family_id: str,\n    payload: bytes,\n    *,\n    authority: str,\n    source_record_id: str,\n    source_url: str,\n    retrieved_at: datetime,\n    media_type: str,\n    schema_signature: str | None = None,\n    record_count: int | None = None,\n    headers: dict[str, str] | None = None,\n    data_dir: Path | str | None = None,\n) -> tuple[Manifestation, Path]:\n    """Freeze through the canonical SourceManifestation runtime.\n\n    store.py owns operational indexes/projections only. Exact source bytes and\n    immutable manifestation receipts are owned by runtime.py.\n    """\n    paths = source_intelligence_paths(data_dir)\n    artifact = RawArtifact(\n        source_family_id=source_family_id,\n        locator=source_url,\n        content=payload,\n        media_type=media_type,\n        retrieved_at_iso=retrieved_at.astimezone(timezone.utc).isoformat(),\n    )\n    frozen = persist_source_manifestation(\n        paths.runtime_root,\n        artifact,\n        schema_fingerprint=schema_signature,\n        record_count=record_count,\n        state="RAW_FROZEN_NOT_PARSED",\n    )\n    lowered = {str(k).lower(): str(v) for k, v in (headers or {}).items()}\n    manifestation = Manifestation(\n        manifestation_id=frozen.manifestation_id,\n        source_authority=authority,\n        source_system=source_family_id,\n        source_record_id=source_record_id,\n        source_url=source_url,\n        retrieved_at_utc=retrieved_at.astimezone(timezone.utc),\n        byte_sha256=frozen.byte_sha256,\n        schema_signature=schema_signature,\n        record_count=record_count,\n        http_etag=lowered.get("etag"),\n        http_last_modified=lowered.get("last-modified"),\n    )\n    target = (\n        paths.runtime_root\n        / "objects"\n        / "sha256"\n        / frozen.byte_sha256[:2]\n        / frozen.byte_sha256\n    )\n    return manifestation, target\n\n\ndef load_manifestations(data_dir: Path | str | None = None) -> list[Manifestation]:
    path = source_intelligence_paths(data_dir).manifestations
    if not path.is_file():
        return []
    rows: list[Manifestation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(Manifestation.model_validate(json.loads(line)))
    return rows


def append_manifestation(
    manifestation: Manifestation,
    data_dir: Path | str | None = None,
) -> bool:
    """Append once by manifestation_id. Existing IDs must be byte-identical."""
    paths = source_intelligence_paths(data_dir)
    current = load_manifestations(paths.data_dir)
    by_id = {item.manifestation_id: item for item in current}
    existing = by_id.get(manifestation.manifestation_id)
    if existing is not None:
        if existing.byte_sha256 != manifestation.byte_sha256:
            raise ValueError("manifestation id collision with different bytes")
        return False
    current.append(manifestation)
    text = "".join(
        json.dumps(item.model_dump(mode="json", exclude_none=True), sort_keys=True) + "\n"
        for item in current
    )
    _atomic_write(paths.manifestations, text)
    return True


def load_receipts(data_dir: Path | str | None = None) -> dict[str, SourceRuntimeReceipt]:
    path = source_intelligence_paths(data_dir).receipts
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != RECEIPTS_SCHEMA:
        raise ValueError("unsupported Source Intelligence receipt schema")
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("Source Intelligence receipts.sources must be an object")
    return {
        source_id: SourceRuntimeReceipt.model_validate(value)
        for source_id, value in sources.items()
    }


def record_receipt(
    source_family_id: str,
    *,
    state: SourceAttemptState,
    attempted_at: datetime,
    manifestation: Manifestation | None = None,
    schema_fingerprint: str | None = None,
    record_count: int | None = None,
    adapter_version: str | None = None,
    error: str | None = None,
    data_dir: Path | str | None = None,
) -> SourceRuntimeReceipt:
    """Record latest attempt while preserving the last successful manifestation on failure."""
    paths = source_intelligence_paths(data_dir)
    receipts = load_receipts(paths.data_dir)
    previous = receipts.get(source_family_id)

    current_manifestation_id = previous.current_manifestation_id if previous else None
    previous_manifestation_id = previous.previous_manifestation_id if previous else None
    current_sha256 = previous.current_sha256 if previous else None
    last_success = previous.last_success if previous else None
    previous_schema = previous.schema_fingerprint if previous else None
    previous_count = previous.record_count if previous else None

    if state == SourceAttemptState.PASS:
        if manifestation is None:
            raise ValueError("PASS receipt requires a manifestation")
        if current_manifestation_id != manifestation.manifestation_id:
            previous_manifestation_id = current_manifestation_id
        current_manifestation_id = manifestation.manifestation_id
        current_sha256 = manifestation.byte_sha256
        last_success = attempted_at.astimezone(timezone.utc)
        previous_schema = schema_fingerprint
        previous_count = record_count
        error = None

    receipt = SourceRuntimeReceipt(
        source_family_id=source_family_id,
        last_attempt=attempted_at.astimezone(timezone.utc),
        last_status=state,
        last_error=error,
        last_success=last_success,
        current_manifestation_id=current_manifestation_id,
        previous_manifestation_id=previous_manifestation_id,
        current_sha256=current_sha256,
        schema_fingerprint=previous_schema,
        record_count=previous_count,
        adapter_version=adapter_version or (previous.adapter_version if previous else None),
    )
    receipts[source_family_id] = receipt
    payload: dict[str, Any] = {
        "schema_version": RECEIPTS_SCHEMA,
        "sources": {
            source_id: value.model_dump(mode="json", exclude_none=True)
            for source_id, value in sorted(receipts.items())
        },
    }
    _atomic_write(paths.receipts, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return receipt
