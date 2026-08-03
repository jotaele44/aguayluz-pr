"""Research-only fungal occurrence evidence foundation.

This module stores, validates, and adjudicates evidence. It intentionally
performs no habitat suitability, connectivity, location ranking,
infrastructure inference, notification, or control action.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker

EvidenceTier = Literal["T1", "T2", "T3", "T4"]
ReviewStatus = Literal["accepted", "needs_review", "rejected", "blocked"]
CoordinateConfidence = Literal["exact", "approximate", "centroid", "unknown"]
CoordinateDatum = Literal["WGS84", "NAD83", "unknown"]
CoordinateMethod = Literal[
    "gps",
    "map",
    "centroid",
    "geocoded",
    "reported",
    "unknown",
]
TaxonomicConfidence = Literal[
    "specimen_verified",
    "expert_verified",
    "photo_supported",
    "reported",
    "unknown",
]
TemporalPrecision = Literal[
    "exact",
    "day",
    "month",
    "year",
    "historical",
    "unknown",
]
AppendStatus = Literal["inserted", "replay"]

SCHEMA_VERSION = "1.1.0"
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
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "schemas"
    / "fungal_occurrence.schema.json"
)
_LEDGER_TABLES = (
    "source_records",
    "occurrences",
    "duplicate_links",
    "adjudications",
    "policy_decisions",
    "dataset_registry",
    "import_receipts",
    "supersessions",
)


@dataclass(frozen=True)
class FungalOccurrenceRecord:
    occurrence_id: str
    source_id: str
    observed_at: str | None
    taxon_name: str | None
    latitude: float | None
    longitude: float | None
    evidence_tier: EvidenceTier
    source_record_id: str | None = None
    review_status: ReviewStatus = "needs_review"
    coordinate_confidence: CoordinateConfidence = "unknown"
    coordinate_uncertainty_m: float | None = None
    coordinate_datum: CoordinateDatum = "unknown"
    coordinate_method: CoordinateMethod = "unknown"
    taxonomic_confidence: TaxonomicConfidence = "unknown"
    temporal_precision: TemporalPrecision = "unknown"
    sensitive: bool = False
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

    def payload_fingerprint(self) -> str:
        return _sha256_json(self.canonical_payload())

    def source_assertion_fingerprint(self) -> str:
        payload = self.canonical_payload()
        payload.pop("occurrence_id")
        return _sha256_json(payload)

    def source_record_key(self) -> str:
        source_record_id = self.source_record_id or self.occurrence_id
        return _sha256_text(f"{self.source_id}\x1f{source_record_id}")

    def duplicate_candidate_fingerprint(self) -> str | None:
        if (
            not self.taxon_name
            or not self.observed_at
            or self.latitude is None
            or self.longitude is None
        ):
            return None
        candidate = {
            "taxon_name": self.taxon_name.strip().casefold(),
            "observed_at": self.observed_at,
            "temporal_precision": self.temporal_precision,
            "latitude": round(self.latitude, 6),
            "longitude": round(self.longitude, 6),
            "coordinate_uncertainty_m": self.coordinate_uncertainty_m,
            "coordinate_datum": self.coordinate_datum,
            "municipality": (
                self.municipality.strip().casefold()
                if self.municipality
                else None
            ),
            "substrate": (
                self.substrate.strip().casefold() if self.substrate else None
            ),
        }
        return _sha256_json(candidate)


@dataclass(frozen=True)
class AppendResult:
    status: AppendStatus
    occurrence_id: str
    duplicate_candidates_linked: int = 0


@dataclass(frozen=True)
class ImportReceipt:
    run_id: str
    source_id: str
    started_at: str
    completed_at: str
    input_sha256: str
    records_seen: int
    records_inserted: int
    exact_replays_blocked: int
    duplicate_candidates_linked: int
    records_rejected: int
    schema_version: str = SCHEMA_VERSION
    status: Literal["complete", "partial", "failed"] = "complete"
    error_code: str | None = None


class ImportFailedError(RuntimeError):
    """Raised after a failed import receipt has been committed."""

    def __init__(self, receipt: ImportReceipt) -> None:
        super().__init__(receipt.error_code or "import_failed")
        self.receipt = receipt


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
    source_record_key TEXT NOT NULL UNIQUE,
    payload_fingerprint TEXT NOT NULL,
    source_assertion_fingerprint TEXT NOT NULL,
    duplicate_candidate_fingerprint TEXT,
    schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source_records(source_id),
    appended_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_occurrences_duplicate_candidate
ON occurrences(duplicate_candidate_fingerprint);
CREATE TABLE IF NOT EXISTS duplicate_links (
    link_id TEXT PRIMARY KEY,
    left_occurrence_id TEXT NOT NULL REFERENCES occurrences(occurrence_id),
    right_occurrence_id TEXT NOT NULL REFERENCES occurrences(occurrence_id),
    link_type TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(left_occurrence_id, right_occurrence_id, link_type)
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
    actor TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS supersessions (
    supersession_id TEXT PRIMARY KEY,
    predecessor_occurrence_id TEXT NOT NULL UNIQUE
        REFERENCES occurrences(occurrence_id),
    successor_occurrence_id TEXT NOT NULL UNIQUE
        REFERENCES occurrences(occurrence_id),
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    policy_basis TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return _sha256_text(encoded)


@cache
def _occurrence_validator() -> Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_fungal_occurrence(record: FungalOccurrenceRecord) -> list[str]:
    errors = sorted(
        _occurrence_validator().iter_errors(record.canonical_payload()),
        key=lambda item: list(item.absolute_path),
    )
    return [f"{error.json_path}: {error.message}" for error in errors]


def _install_append_only_triggers(conn: sqlite3.Connection) -> None:
    for table in _LEDGER_TABLES:
        conn.executescript(
            f"""
            CREATE TRIGGER IF NOT EXISTS deny_update_{table}
            BEFORE UPDATE ON {table}
            BEGIN
                SELECT RAISE(ABORT, 'append_only:{table}:update');
            END;
            CREATE TRIGGER IF NOT EXISTS deny_delete_{table}
            BEFORE DELETE ON {table}
            BEGIN
                SELECT RAISE(ABORT, 'append_only:{table}:delete');
            END;
            """
        )


def initialize_database(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    _install_append_only_triggers(conn)
    conn.commit()
    return conn


def _commit(conn: sqlite3.Connection, enabled: bool) -> None:
    if enabled:
        conn.commit()


def _require_nonempty(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"missing_{name}")


def _require_sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in value
    ):
        raise ValueError(f"invalid_{name}_sha256")


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
    _commit_write: bool = True,
) -> Literal["inserted", "replay"]:
    _require_nonempty("source_id", source_id)
    _require_nonempty("source_title", title)
    _require_nonempty("source_type", source_type)
    _require_sha256("source", input_sha256)
    existing = conn.execute(
        "SELECT title,source_type,source_uri,input_sha256,license,notes "
        "FROM source_records WHERE source_id=?",
        (source_id,),
    ).fetchone()
    proposed = (
        title,
        source_type,
        source_uri,
        input_sha256,
        license_name,
        notes,
    )
    if existing is not None:
        if tuple(existing) == proposed:
            return "replay"
        raise ValueError("source_id_conflict")
    conn.execute(
        """
        INSERT INTO source_records(
            source_id,title,source_type,source_uri,retrieved_at,
            input_sha256,license,notes
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
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
    _commit(conn, _commit_write)
    return "inserted"


def _require_occurrence(
    conn: sqlite3.Connection,
    occurrence_id: str,
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM occurrences WHERE occurrence_id=?",
        (occurrence_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown_occurrence:{occurrence_id}")
    return row


def append_duplicate_link(
    conn: sqlite3.Connection,
    *,
    left_occurrence_id: str,
    right_occurrence_id: str,
    link_type: str,
    reason: str,
    actor: str,
    status: ReviewStatus = "needs_review",
    _commit_write: bool = True,
) -> Literal["inserted", "replay"]:
    _require_nonempty("link_type", link_type)
    _require_nonempty("duplicate_reason", reason)
    _require_nonempty("duplicate_actor", actor)
    if status not in {"accepted", "needs_review", "rejected", "blocked"}:
        raise ValueError("invalid_duplicate_link_status")
    if left_occurrence_id == right_occurrence_id:
        raise ValueError("self_duplicate_link")
    _require_occurrence(conn, left_occurrence_id)
    _require_occurrence(conn, right_occurrence_id)
    left, right = sorted((left_occurrence_id, right_occurrence_id))
    link_id = _sha256_text(
        f"duplicate-link\x1f{left}\x1f{right}\x1f{link_type}"
    )
    existing = conn.execute(
        "SELECT 1 FROM duplicate_links WHERE link_id=?",
        (link_id,),
    ).fetchone()
    if existing is not None:
        return "replay"
    conn.execute(
        """
        INSERT INTO duplicate_links(
            link_id,left_occurrence_id,right_occurrence_id,link_type,
            status,reason,actor,created_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (link_id, left, right, link_type, status, reason, actor, utc_now()),
    )
    _commit(conn, _commit_write)
    return "inserted"


def _link_duplicate_candidates(
    conn: sqlite3.Connection,
    record: FungalOccurrenceRecord,
    candidate_fingerprint: str | None,
) -> int:
    if candidate_fingerprint is None:
        return 0
    rows = conn.execute(
        """
        SELECT occurrence_id
        FROM occurrences
        WHERE duplicate_candidate_fingerprint=?
          AND occurrence_id<>?
          AND source_id<>?
        ORDER BY occurrence_id
        """,
        (candidate_fingerprint, record.occurrence_id, record.source_id),
    ).fetchall()
    created = 0
    for row in rows:
        result = append_duplicate_link(
            conn,
            left_occurrence_id=row["occurrence_id"],
            right_occurrence_id=record.occurrence_id,
            link_type="cross_source_candidate",
            reason="matching_duplicate_candidate_fingerprint",
            actor="system:import",
            _commit_write=False,
        )
        created += result == "inserted"
    return created


def append_fungal_occurrence(
    conn: sqlite3.Connection,
    record: FungalOccurrenceRecord,
    *,
    _commit_write: bool = True,
) -> AppendResult:
    errors = validate_fungal_occurrence(record)
    if errors:
        raise ValueError(
            {"error": "invalid_fungal_occurrence", "violations": errors}
        )
    payload = record.canonical_payload()
    payload_fingerprint = record.payload_fingerprint()
    source_assertion_fingerprint = record.source_assertion_fingerprint()
    source_record_key = record.source_record_key()
    existing = conn.execute(
        """
        SELECT occurrence_id,source_record_key,payload_fingerprint,
               source_assertion_fingerprint
        FROM occurrences
        WHERE occurrence_id=? OR source_record_key=?
        """,
        (record.occurrence_id, source_record_key),
    ).fetchone()
    if existing is not None:
        exact_occurrence_replay = (
            existing["occurrence_id"] == record.occurrence_id
            and existing["payload_fingerprint"] == payload_fingerprint
        )
        exact_source_record_replay = (
            existing["source_record_key"] == source_record_key
            and existing["source_assertion_fingerprint"]
            == source_assertion_fingerprint
        )
        if exact_occurrence_replay or exact_source_record_replay:
            return AppendResult("replay", existing["occurrence_id"])
        raise ValueError("source_record_or_occurrence_id_conflict")

    candidate_fingerprint = record.duplicate_candidate_fingerprint()
    conn.execute(
        """
        INSERT INTO occurrences(
            occurrence_id,source_record_key,payload_fingerprint,
            source_assertion_fingerprint,duplicate_candidate_fingerprint,
            schema_version,payload_json,source_id,appended_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            record.occurrence_id,
            source_record_key,
            payload_fingerprint,
            source_assertion_fingerprint,
            candidate_fingerprint,
            record.schema_version,
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
            record.source_id,
            utc_now(),
        ),
    )
    linked = _link_duplicate_candidates(conn, record, candidate_fingerprint)
    _commit(conn, _commit_write)
    return AppendResult("inserted", record.occurrence_id, linked)


def append_adjudication(
    conn: sqlite3.Connection,
    *,
    adjudication_id: str,
    occurrence_id: str,
    actor: str,
    decision: ReviewStatus,
    reason: str,
    _commit_write: bool = True,
) -> None:
    _require_nonempty("adjudication_id", adjudication_id)
    _require_nonempty("adjudication_actor", actor)
    _require_nonempty("adjudication_reason", reason)
    _require_occurrence(conn, occurrence_id)
    if decision not in {"accepted", "needs_review", "rejected", "blocked"}:
        raise ValueError("invalid_adjudication_decision")
    conn.execute(
        """
        INSERT INTO adjudications(
            adjudication_id,occurrence_id,actor,decision,reason,created_at
        ) VALUES(?,?,?,?,?,?)
        """,
        (adjudication_id, occurrence_id, actor, decision, reason, utc_now()),
    )
    _commit(conn, _commit_write)


def append_policy_decision(
    conn: sqlite3.Connection,
    *,
    decision_id: str,
    subject_type: str,
    subject_id: str,
    policy: str,
    outcome: str,
    actor: str,
    reason: str,
    _commit_write: bool = True,
) -> None:
    _require_nonempty("policy_decision_id", decision_id)
    _require_nonempty("policy_subject_type", subject_type)
    _require_nonempty("policy_subject_id", subject_id)
    _require_nonempty("policy_name", policy)
    _require_nonempty("policy_outcome", outcome)
    _require_nonempty("policy_actor", actor)
    _require_nonempty("policy_reason", reason)
    if subject_type == "occurrence":
        _require_occurrence(conn, subject_id)
    conn.execute(
        """
        INSERT INTO policy_decisions(
            decision_id,subject_type,subject_id,policy,outcome,
            actor,reason,created_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            decision_id,
            subject_type,
            subject_id,
            policy,
            outcome,
            actor,
            reason,
            utc_now(),
        ),
    )
    _commit(conn, _commit_write)


def register_dataset(
    conn: sqlite3.Connection,
    *,
    dataset_id: str,
    title: str,
    version: str,
    sha256: str,
    status: str,
    metadata: dict[str, Any] | None = None,
    _commit_write: bool = True,
) -> None:
    _require_nonempty("dataset_id", dataset_id)
    _require_nonempty("dataset_title", title)
    _require_nonempty("dataset_version", version)
    _require_nonempty("dataset_status", status)
    _require_sha256("dataset", sha256)
    conn.execute(
        """
        INSERT INTO dataset_registry(
            dataset_id,title,version,sha256,status,registered_at,metadata_json
        ) VALUES(?,?,?,?,?,?,?)
        """,
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
    _commit(conn, _commit_write)


def append_supersession(
    conn: sqlite3.Connection,
    *,
    supersession_id: str,
    predecessor_occurrence_id: str,
    successor_occurrence_id: str,
    actor: str,
    reason: str,
    policy_basis: str,
    _commit_write: bool = True,
) -> None:
    _require_nonempty("supersession_id", supersession_id)
    _require_nonempty("supersession_actor", actor)
    _require_nonempty("supersession_reason", reason)
    _require_nonempty("supersession_policy_basis", policy_basis)
    if predecessor_occurrence_id == successor_occurrence_id:
        raise ValueError("self_supersession")
    _require_occurrence(conn, predecessor_occurrence_id)
    _require_occurrence(conn, successor_occurrence_id)
    if conn.execute(
        """
        SELECT 1 FROM supersessions
        WHERE predecessor_occurrence_id=?
        """,
        (predecessor_occurrence_id,),
    ).fetchone():
        raise ValueError("predecessor_already_superseded")
    if conn.execute(
        """
        SELECT 1 FROM supersessions
        WHERE successor_occurrence_id=?
        """,
        (successor_occurrence_id,),
    ).fetchone():
        raise ValueError("successor_already_has_predecessor")

    cursor = successor_occurrence_id
    visited: set[str] = set()
    while True:
        if cursor == predecessor_occurrence_id:
            raise ValueError("supersession_cycle")
        if cursor in visited:
            raise ValueError("existing_supersession_cycle")
        visited.add(cursor)
        row = conn.execute(
            """
            SELECT successor_occurrence_id
            FROM supersessions
            WHERE predecessor_occurrence_id=?
            """,
            (cursor,),
        ).fetchone()
        if row is None:
            break
        cursor = row["successor_occurrence_id"]

    conn.execute(
        """
        INSERT INTO supersessions(
            supersession_id,predecessor_occurrence_id,
            successor_occurrence_id,actor,reason,policy_basis,created_at
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            supersession_id,
            predecessor_occurrence_id,
            successor_occurrence_id,
            actor,
            reason,
            policy_basis,
            utc_now(),
        ),
    )
    _commit(conn, _commit_write)


def resolve_effective_occurrence_id(
    conn: sqlite3.Connection,
    occurrence_id: str,
) -> str:
    _require_occurrence(conn, occurrence_id)
    cursor = occurrence_id
    visited: set[str] = set()
    while True:
        if cursor in visited:
            raise RuntimeError("supersession_cycle_detected")
        visited.add(cursor)
        row = conn.execute(
            """
            SELECT successor_occurrence_id
            FROM supersessions
            WHERE predecessor_occurrence_id=?
            """,
            (cursor,),
        ).fetchone()
        if row is None:
            return cursor
        cursor = row["successor_occurrence_id"]


def _receipt_from_row(row: sqlite3.Row) -> ImportReceipt:
    return ImportReceipt(**json.loads(row["payload_json"]))


def _validate_receipt(receipt: ImportReceipt) -> None:
    counts = (
        receipt.records_seen,
        receipt.records_inserted,
        receipt.exact_replays_blocked,
        receipt.duplicate_candidates_linked,
        receipt.records_rejected,
    )
    if any(count < 0 for count in counts):
        raise ValueError("negative_receipt_count")
    accounted = (
        receipt.records_inserted
        + receipt.exact_replays_blocked
        + receipt.records_rejected
    )
    if receipt.records_seen != accounted:
        raise ValueError("receipt_accounting_mismatch")
    if receipt.status == "failed" and not receipt.error_code:
        raise ValueError("failed_receipt_missing_error_code")


def _append_receipt(
    conn: sqlite3.Connection,
    receipt: ImportReceipt,
    *,
    _commit_write: bool,
) -> None:
    _validate_receipt(receipt)
    conn.execute(
        """
        INSERT INTO import_receipts(run_id,payload_json,appended_at)
        VALUES(?,?,?)
        """,
        (
            receipt.run_id,
            json.dumps(asdict(receipt), sort_keys=True),
            utc_now(),
        ),
    )
    _commit(conn, _commit_write)


def import_records(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    input_bytes: bytes,
    records: Iterable[FungalOccurrenceRecord],
    run_id: str,
) -> ImportReceipt:
    input_sha256 = hashlib.sha256(input_bytes).hexdigest()
    prior = conn.execute(
        "SELECT payload_json FROM import_receipts WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if prior is not None:
        receipt = _receipt_from_row(prior)
        if receipt.source_id == source_id and receipt.input_sha256 == input_sha256:
            return receipt
        raise ValueError("run_id_conflict")

    started = utc_now()
    seen = inserted = replays = candidates = rejected = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for record in records:
            seen += 1
            if record.source_id != source_id:
                rejected += 1
                continue
            try:
                result = append_fungal_occurrence(
                    conn,
                    record,
                    _commit_write=False,
                )
            except ValueError:
                rejected += 1
                continue
            inserted += result.status == "inserted"
            replays += result.status == "replay"
            candidates += result.duplicate_candidates_linked
        receipt = ImportReceipt(
            run_id=run_id,
            source_id=source_id,
            started_at=started,
            completed_at=utc_now(),
            input_sha256=input_sha256,
            records_seen=seen,
            records_inserted=inserted,
            exact_replays_blocked=replays,
            duplicate_candidates_linked=candidates,
            records_rejected=rejected,
            status="complete" if rejected == 0 else "partial",
        )
        _append_receipt(conn, receipt, _commit_write=False)
        conn.commit()
        return receipt
    except Exception as exc:
        conn.rollback()
        failed = ImportReceipt(
            run_id=run_id,
            source_id=source_id,
            started_at=started,
            completed_at=utc_now(),
            input_sha256=input_sha256,
            records_seen=seen,
            records_inserted=0,
            exact_replays_blocked=0,
            duplicate_candidates_linked=0,
            records_rejected=seen,
            status="failed",
            error_code=type(exc).__name__,
        )
        _append_receipt(conn, failed, _commit_write=True)
        raise ImportFailedError(failed) from exc


def safe_fungal_occurrence_view(
    conn: sqlite3.Connection,
    record: FungalOccurrenceRecord,
    *,
    policy_decision_id: str | None = None,
) -> dict[str, Any]:
    payload = record.canonical_payload()
    if not record.sensitive:
        return payload

    allow_exact = False
    if policy_decision_id:
        row = conn.execute(
            """
            SELECT subject_type,subject_id,policy,outcome
            FROM policy_decisions
            WHERE decision_id=?
            """,
            (policy_decision_id,),
        ).fetchone()
        allow_exact = bool(
            row
            and row["subject_type"] == "occurrence"
            and row["subject_id"] == record.occurrence_id
            and row["policy"] == "sensitive_coordinate_disclosure"
            and row["outcome"] == "allow_exact_coordinates"
        )
    if not allow_exact:
        payload["latitude"] = None
        payload["longitude"] = None
        payload["coordinate_uncertainty_m"] = None
        payload["coordinate_confidence"] = "unknown"
        payload["coordinate_method"] = "unknown"
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
