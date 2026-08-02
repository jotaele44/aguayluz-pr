"""Research-only fungal occurrence foundation.

This module stores and validates evidence. It intentionally performs no habitat
suitability, connectivity, location ranking, infrastructure inference, or public
coordinate disclosure.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

EvidenceTier = Literal["T1", "T2", "T3", "T4"]
ReviewStatus = Literal["unreviewed", "needs_review", "accepted", "rejected"]
CoordinateConfidence = Literal["exact", "approximate", "centroid", "unknown"]
TaxonomicConfidence = Literal[
    "specimen_verified",
    "expert_verified",
    "photo_supported",
    "reported",
    "unknown",
]
TemporalConfidence = Literal["exact", "day", "month", "year", "historical", "unknown"]

SCHEMA_VERSION = "1.0.0"
RESEARCH_ONLY = True
ANALYTICS_STATUS = "model_not_calibrated"
PROHIBITED_ANALYTICS = frozenset(
    {
        "habitat_suitability",
        "connectivity",
        "location_ranking",
        "public_exact_coordinates",
        "infrastructure_inference",
        "notifications",
        "control_actions",
    }
)


@dataclass(frozen=True)
class OccurrenceRecord:
    occurrence_id: str
    source_id: str
    observed_at: str | None
    taxon_name: str | None
    latitude: float | None
    longitude: float | None
    evidence_tier: EvidenceTier
    review_status: ReviewStatus = "unreviewed"
    coordinate_confidence: CoordinateConfidence = "unknown"
    taxonomic_confidence: TaxonomicConfidence = "unknown"
    temporal_confidence: TemporalConfidence = "unknown"
    sensitive: bool = False
    source_record_id: str | None = None
    municipality: str | None = None
    substrate: str | None = None
    observer: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    notes: str | None = None
    schema_version: str = SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = sorted(set(self.evidence_refs))
        return payload

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ImportReceipt:
    run_id: str
    source_id: str
    started_at: str
    completed_at: str
    input_sha256: str
    records_seen: int
    records_inserted: int
    duplicates_blocked: int
    records_rejected: int
    schema_version: str = SCHEMA_VERSION
    status: Literal["complete", "partial", "failed"] = "complete"


DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS source_records (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT,
    retrieved_at TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    license TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS occurrences (
    occurrence_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source_records(source_id),
    appended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS duplicate_links (
    duplicate_occurrence_id TEXT PRIMARY KEY,
    canonical_occurrence_id TEXT NOT NULL REFERENCES occurrences(occurrence_id),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adjudications (
    adjudication_id TEXT PRIMARY KEY,
    occurrence_id TEXT NOT NULL REFERENCES occurrences(occurrence_id),
    actor TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_decisions (
    decision_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    policy TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_registry (
    dataset_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS import_receipts (
    run_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    appended_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def initialize_database(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript(DDL)
    conn.commit()
    return conn


def validate_occurrence(record: OccurrenceRecord) -> list[str]:
    errors: list[str] = []
    if record.schema_version != SCHEMA_VERSION:
        errors.append("unsupported_schema_version")
    if not record.occurrence_id.strip():
        errors.append("missing_occurrence_id")
    if not record.source_id.strip():
        errors.append("missing_source_id")
    if (record.latitude is None) != (record.longitude is None):
        errors.append("incomplete_coordinates")
    if record.latitude is not None and not -90 <= record.latitude <= 90:
        errors.append("latitude_out_of_range")
    if record.longitude is not None and not -180 <= record.longitude <= 180:
        errors.append("longitude_out_of_range")
    if record.coordinate_confidence == "exact" and record.latitude is None:
        errors.append("exact_coordinates_missing")
    if record.taxonomic_confidence == "specimen_verified" and not record.evidence_refs:
        errors.append("specimen_evidence_missing")
    return errors


def append_source(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    title: str,
    source_type: str,
    input_sha256: str,
    source_uri: str | None = None,
    license_name: str | None = None,
    notes: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO source_records(source_id,title,source_type,source_uri,retrieved_at,input_sha256,license,notes) VALUES(?,?,?,?,?,?,?,?)",
        (
            source_id,
            title,
            source_type,
            source_uri,
            utc_now(),
            input_sha256,
            license_name,
            notes,
        ),
    )
    conn.commit()


def append_occurrence(
    conn: sqlite3.Connection,
    record: OccurrenceRecord,
) -> Literal["inserted", "duplicate"]:
    errors = validate_occurrence(record)
    if errors:
        raise ValueError({"error": "invalid_occurrence", "violations": errors})
    payload = json.dumps(
        record.canonical_payload(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    try:
        conn.execute(
            "INSERT INTO occurrences(occurrence_id,fingerprint,schema_version,payload_json,source_id,appended_at) VALUES(?,?,?,?,?,?)",
            (
                record.occurrence_id,
                record.fingerprint(),
                record.schema_version,
                payload,
                record.source_id,
                utc_now(),
            ),
        )
        conn.commit()
        return "inserted"
    except sqlite3.IntegrityError as exc:
        if "fingerprint" in str(exc) or "occurrence_id" in str(exc):
            conn.rollback()
            return "duplicate"
        raise


def register_dataset(
    conn: sqlite3.Connection,
    *,
    dataset_id: str,
    title: str,
    version: str,
    sha256: str,
    status: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO dataset_registry(dataset_id,title,version,sha256,status,registered_at,metadata_json) VALUES(?,?,?,?,?,?,?)",
        (
            dataset_id,
            title,
            version,
            sha256,
            status,
            utc_now(),
            json.dumps(metadata or {}, sort_keys=True),
        ),
    )
    conn.commit()


def write_receipt(conn: sqlite3.Connection, receipt: ImportReceipt) -> None:
    conn.execute(
        "INSERT INTO import_receipts(run_id,payload_json,appended_at) VALUES(?,?,?)",
        (receipt.run_id, json.dumps(asdict(receipt), sort_keys=True), utc_now()),
    )
    conn.commit()


def import_records(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    input_bytes: bytes,
    records: Iterable[OccurrenceRecord],
    run_id: str,
) -> ImportReceipt:
    started = utc_now()
    seen = inserted = duplicates = rejected = 0
    for record in records:
        seen += 1
        if record.source_id != source_id:
            rejected += 1
            continue
        try:
            result = append_occurrence(conn, record)
        except ValueError:
            rejected += 1
            continue
        inserted += result == "inserted"
        duplicates += result == "duplicate"
    receipt = ImportReceipt(
        run_id=run_id,
        source_id=source_id,
        started_at=started,
        completed_at=utc_now(),
        input_sha256=hashlib.sha256(input_bytes).hexdigest(),
        records_seen=seen,
        records_inserted=inserted,
        duplicates_blocked=duplicates,
        records_rejected=rejected,
        status="complete" if rejected == 0 else "partial",
    )
    write_receipt(conn, receipt)
    return receipt


def safe_occurrence_view(
    record: OccurrenceRecord,
    *,
    authorized_sensitive: bool = False,
) -> dict[str, Any]:
    payload = record.canonical_payload()
    if record.sensitive and not authorized_sensitive:
        payload["latitude"] = None
        payload["longitude"] = None
        payload["coordinate_confidence"] = "unknown"
        payload["coordinate_policy"] = "withheld_sensitive_taxon"
    return payload


def analytics_unavailable(capability: str) -> dict[str, Any]:
    if capability not in PROHIBITED_ANALYTICS:
        capability = "unknown_analytics"
    return {
        "status": ANALYTICS_STATUS,
        "capability": capability,
        "research_only": RESEARCH_ONLY,
        "available": False,
        "reason": (
            "Phase 0 stores and validates evidence only; "
            "no calibrated ecological model is installed."
        ),
    }
