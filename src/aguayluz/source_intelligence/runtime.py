"""Immutable source-manifestation and health-receipt runtime."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.base import RawArtifact
from .models import SourceHealth

MAX_SOURCE_BYTES = 100 * 1024 * 1024
_SOURCE_ID_RE = re.compile(r"^[A-Z0-9_]+$")


@dataclass(frozen=True)
class SourceManifestation:
    manifestation_id: str
    source_family_id: str
    locator: str
    retrieved_at_utc: str
    byte_sha256: str
    byte_count: int
    media_type: str
    schema_fingerprint: str | None = None
    record_count: int | None = None
    state: str = "RAW_FROZEN_NOT_PARSED"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _manifestation_id(artifact: RawArtifact, digest: str) -> str:
    identity = canonical_json_bytes(
        {
            "source_family_id": artifact.source_family_id,
            "locator": artifact.locator,
            "retrieved_at_iso": artifact.retrieved_at_iso,
            "byte_sha256": digest,
        }
    )
    return "SRCM_" + hashlib.sha256(identity).hexdigest()[:24]


def _atomic_no_clobber(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"immutable path already contains different bytes: {path}")
        return
    fd, tmp_name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp_name, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError(
                    f"concurrent writer changed immutable path: {path}"
                ) from None
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def persist_source_manifestation(
    root: Path,
    artifact: RawArtifact,
    *,
    schema_fingerprint: str | None = None,
    record_count: int | None = None,
    state: str = "RAW_FROZEN_NOT_PARSED",
) -> SourceManifestation:
    if not _SOURCE_ID_RE.fullmatch(artifact.source_family_id):
        raise ValueError("source_family_id must be a registered-style uppercase identifier")
    if not artifact.content or len(artifact.content) > MAX_SOURCE_BYTES:
        raise ValueError("source artifact is empty or exceeds the size bound")
    if record_count is not None and record_count < 0:
        raise ValueError("record_count cannot be negative")

    digest = hashlib.sha256(artifact.content).hexdigest()
    object_path = root / "objects" / "sha256" / digest[:2] / digest
    _atomic_no_clobber(object_path, artifact.content)

    manifestation = SourceManifestation(
        manifestation_id=_manifestation_id(artifact, digest),
        source_family_id=artifact.source_family_id,
        locator=artifact.locator,
        retrieved_at_utc=artifact.retrieved_at_iso,
        byte_sha256=digest,
        byte_count=len(artifact.content),
        media_type=artifact.media_type,
        schema_fingerprint=schema_fingerprint,
        record_count=record_count,
        state=state,
    )
    receipt_path = (
        root
        / "manifestations"
        / artifact.source_family_id
        / f"{manifestation.manifestation_id}.json"
    )
    receipt_bytes = canonical_json_bytes(asdict(manifestation)) + b"\n"
    _atomic_no_clobber(receipt_path, receipt_bytes)
    return manifestation


def verify_source_manifestation(root: Path, manifestation: SourceManifestation) -> None:
    object_path = (
        root
        / "objects"
        / "sha256"
        / manifestation.byte_sha256[:2]
        / manifestation.byte_sha256
    )
    if not object_path.is_file():
        raise ValueError("content-addressed source object is missing")
    raw = object_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != manifestation.byte_sha256:
        raise ValueError("content-addressed source object hash mismatch")
    if len(raw) != manifestation.byte_count:
        raise ValueError("content-addressed source object byte-count mismatch")

    receipt_path = (
        root
        / "manifestations"
        / manifestation.source_family_id
        / f"{manifestation.manifestation_id}.json"
    )
    expected = canonical_json_bytes(asdict(manifestation)) + b"\n"
    if not receipt_path.is_file() or receipt_path.read_bytes() != expected:
        raise ValueError("source manifestation receipt mismatch")


def freeze_health_receipt(
    root: Path,
    health: SourceHealth,
    *,
    checked_at: datetime | None = None,
) -> tuple[str, Path]:
    stamp = checked_at or health.last_check or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        raise ValueError("health receipt timestamp must be timezone-aware")
    payload = {
        "schema_version": "aguayluz.source-health-receipt/v1",
        "checked_at_utc": stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "health": health.model_dump(mode="json"),
    }
    encoded = canonical_json_bytes(payload) + b"\n"
    receipt_sha256 = hashlib.sha256(encoded).hexdigest()
    path = (
        root
        / "health"
        / health.source_family_id
        / f"{receipt_sha256}.json"
    )
    _atomic_no_clobber(path, encoded)
    return receipt_sha256, path


def load_health_receipts(root: Path, source_family_id: str) -> list[dict[str, Any]]:
    folder = root / "health" / source_family_id
    if not folder.is_dir():
        return []
    rows = []
    for path in sorted(folder.glob("*.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows
