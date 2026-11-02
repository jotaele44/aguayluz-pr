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

from .models import SourceAttemptState, SourceRuntimeReceipt

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

    def snapshot_dir(self, source_family_id: str) -> Path:
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


def _manifestation_id(source_family_id: str, digest: str) -> str:
    return f"SOURCEINTEL:{source_family_id}:{digest[:32]}"


def _extension_from_media_type(media_type: str) -> str:
    lowered = media_type.lower()
    if "spreadsheetml.sheet" in lowered:
        return "xlsx"
    if "pdf" in lowered:
        return "pdf"
    if "json" in lowered:
        return "json"
    if "zip" in lowered:
        return "zip"
    if "csv" in lowered:
        return "csv"
    return "bin"


def freeze_artifact(
    source_family_id: str,
    payload: bytes,
    *,
    authority: str,
    source_record_id: str,
    source_url: str,
    retrieved_at: datetime,
    media_type: str,
    schema_signature: str | None = None,
    record_count: int | None = None,
    headers: dict[str, str] | None = None,
    data_dir: Path | str | None = None,
) -> tuple[Manifestation, Path]:
    """Freeze exact bytes before parsing and return the immutable manifestation."""
    digest = sha256(payload).hexdigest()
    paths = source_intelligence_paths(data_dir)
    target_dir = paths.snapshot_dir(source_family_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest}.{_extension_from_media_type(media_type)}"
    if target.exists():
        existing = target.read_bytes()
        if sha256(existing).hexdigest() != digest:
            raise ValueError("content-addressed snapshot hash mismatch")
    else:
        target.write_bytes(payload)

    lowered = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    manifestation = Manifestation(
        manifestation_id=_manifestation_id(source_family_id, digest),
        source_authority=authority,
        source_system=source_family_id,
        source_record_id=source_record_id,
        source_url=source_url,
        retrieved_at_utc=retrieved_at.astimezone(timezone.utc),
        byte_sha256=digest,
        schema_signature=schema_signature,
        record_count=record_count,
        http_etag=lowered.get("etag"),
        http_last_modified=lowered.get("last-modified"),
    )
    return manifestation, target


def load_manifestations(data_dir: Path | str | None = None) -> list[Manifestation]:
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
