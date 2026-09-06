"""Bounded research-only ingestion for Mycelial Phase 1 Ballot A.

RAW, NORMALIZED and CANONICAL manifestations are separate. This module has no
API/GUI surface and does not implement prediction, suitability, connectivity,
notifications, coordinate disclosure or control actions.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_VERSION = "1.0.0"
AUTHORIZATION_REF = "MYC_BALLOT_A_RESEARCH_INGEST_20260906"
SUPERSEDED_HOLD_REF = "4851413154"
CAPABILITY = "internal_research_ingest_only"
ANALYTICS_STATUS = "model_not_calibrated"

_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "mycelial-phase1" / "v1"
_SCHEMA_FILES = {
    "source_registry_entry": "source-license-provenance.schema.json",
    "provenance_record": "source-license-provenance.schema.json",
    "survey_effort": "sampling-effort.schema.json",
    "taxonomic_evidence": "taxonomic-evidence.schema.json",
    "temporal_match": "temporal-environmental-evidence.schema.json",
    "environmental_evidence_sheet": "temporal-environmental-evidence.schema.json",
    "lifecycle_site": "lifecycle-evidence.schema.json",
    "lifecycle_observation": "lifecycle-evidence.schema.json",
    "media_evidence": "lifecycle-evidence.schema.json",
    "environmental_snapshot": "lifecycle-evidence.schema.json",
    "lifecycle_transition": "lifecycle-evidence.schema.json",
}
_ID_FIELDS = {
    "source_registry_entry": "source_id",
    "provenance_record": "provenance_id",
    "survey_effort": "survey_id",
    "taxonomic_evidence": "assertion_id",
    "temporal_match": "match_id",
    "environmental_evidence_sheet": "predictor_id",
    "lifecycle_site": "site_id",
    "lifecycle_observation": "observation_id",
    "media_evidence": "media_id",
    "environmental_snapshot": "snapshot_id",
    "lifecycle_transition": "transition_id",
}
_TABLES = (
    "raw_batches",
    "raw_records",
    "normalized_records",
    "canonical_records",
    "record_events",
    "ingest_receipts",
)


@dataclass(frozen=True)
class IngestReceipt:
    receipt_id: str
    source_id: str
    batch_id: str
    input_sha256: str
    started_at: str
    completed_at: str
    status: Literal["complete", "partial", "rejected"]
    attempted: int
    accepted: int
    rejected: int
    review_queue: int
    exact_replays: int
    duplicate_candidates: int
    authorization_ref: str = AUTHORIZATION_REF
    superseded_hold_ref: str = SUPERSEDED_HOLD_REF
    capability: str = CAPABILITY
    analytics_status: str = ANALYTICS_STATUS

    def assert_closed(self) -> None:
        if self.attempted != self.accepted + self.rejected + self.review_queue + self.exact_replays:
            raise ValueError("receipt_accounting_mismatch")


DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS raw_batches(
 batch_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, input_sha256 TEXT NOT NULL,
 payload_bytes BLOB NOT NULL, appended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_records(
 raw_record_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES raw_batches(batch_id),
 row_index INTEGER NOT NULL, raw_sha256 TEXT NOT NULL, raw_text TEXT NOT NULL,
 parse_status TEXT NOT NULL, source_record_id TEXT, appended_at TEXT NOT NULL,
 UNIQUE(batch_id,row_index)
);
CREATE TABLE IF NOT EXISTS normalized_records(
 normalized_record_id TEXT PRIMARY KEY,
 raw_record_id TEXT NOT NULL UNIQUE REFERENCES raw_records(raw_record_id),
 record_type TEXT NOT NULL, stable_id TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
 payload_json TEXT NOT NULL, appended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS canonical_records(
 canonical_record_id TEXT PRIMARY KEY, record_type TEXT NOT NULL, stable_id TEXT NOT NULL,
 source_id TEXT NOT NULL, normalized_record_id TEXT NOT NULL REFERENCES normalized_records(normalized_record_id),
 payload_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL, evidence_review_state TEXT,
 active INTEGER NOT NULL CHECK(active IN(0,1)), appended_at TEXT NOT NULL,
 UNIQUE(record_type,stable_id)
);
CREATE TABLE IF NOT EXISTS record_events(
 event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, left_record_id TEXT,
 right_record_id TEXT, raw_record_id TEXT REFERENCES raw_records(raw_record_id),
 basis TEXT NOT NULL, details_json TEXT NOT NULL, appended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingest_receipts(
 receipt_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL UNIQUE REFERENCES raw_batches(batch_id),
 payload_json TEXT NOT NULL, appended_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_myc_canonical_type_id ON canonical_records(record_type,stable_id);
CREATE INDEX IF NOT EXISTS idx_myc_canonical_source ON canonical_records(source_id);
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def initialize_database(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    for table in _TABLES:
        conn.executescript(
            f"""
            CREATE TRIGGER IF NOT EXISTS deny_update_{table}
            BEFORE UPDATE ON {table} BEGIN
              SELECT RAISE(ABORT,'append_only:{table}:update');
            END;
            CREATE TRIGGER IF NOT EXISTS deny_delete_{table}
            BEFORE DELETE ON {table} BEGIN
              SELECT RAISE(ABORT,'append_only:{table}:delete');
            END;
            """
        )
    conn.commit()
    return conn


@cache
def _validator(record_type: str) -> Draft202012Validator:
    try:
        name = _SCHEMA_FILES[record_type]
    except KeyError as exc:
        raise ValueError(f"unsupported_record_type:{record_type}") from exc
    schema = json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _finite(value: Any, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"nonfinite_number:{path}")
    if isinstance(value, dict):
        for key, child in value.items():
            _finite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _finite(child, f"{path}[{index}]")


def validate_record(record: dict[str, Any]) -> list[str]:
    record_type = record.get("record_type")
    if not isinstance(record_type, str):
        return ["$.record_type: missing or non-string"]
    if record.get("schema_version") != SCHEMA_VERSION:
        return [f"$.schema_version: expected {SCHEMA_VERSION}"]
    try:
        _finite(record)
        errors = sorted(_validator(record_type).iter_errors(record), key=lambda e: list(e.absolute_path))
    except ValueError as exc:
        return [str(exc)]
    return [f"{error.json_path}: {error.message}" for error in errors]


def _stable_id(record: dict[str, Any]) -> str:
    record_type = record["record_type"]
    field = _ID_FIELDS.get(record_type)
    if field is None:
        raise ValueError(f"unsupported_record_type:{record_type}")
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing_stable_id:{record_type}:{field}")
    return value


def _canonical_id(record_type: str, stable_id: str) -> str:
    return sha_text(f"mycelial-phase1\x1f{record_type}\x1f{stable_id}")


def _load(conn: sqlite3.Connection, record_type: str, stable_id: str) -> tuple[sqlite3.Row, dict[str, Any]] | None:
    row = conn.execute(
        "SELECT * FROM canonical_records WHERE record_type=? AND stable_id=?",
        (record_type, stable_id),
    ).fetchone()
    return None if row is None else (row, json.loads(row["payload_json"]))


def _require(conn: sqlite3.Connection, record_type: str, stable_id: str) -> dict[str, Any]:
    item = _load(conn, record_type, stable_id)
    if item is None:
        raise ValueError(f"missing_binding:{record_type}:{stable_id}")
    return item[1]


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("datetime_missing_timezone")
    return parsed


def _source(conn: sqlite3.Connection, source_id: str) -> dict[str, Any] | None:
    item = _load(conn, "source_registry_entry", source_id)
    return None if item is None else item[1]


def _retention_gate(source: dict[str, Any]) -> None:
    retention = source["retention"]
    if retention["raw_bytes"] not in {"retain", "restricted_retain"}:
        raise ValueError("source_raw_retention_not_admissible")
    if retention["normalized_records"] not in {"retain", "restricted_retain"}:
        raise ValueError("source_normalized_retention_not_admissible")


def _coord_gate(source: dict[str, Any], mode: str) -> None:
    policy = source["coordinate_retention_policy"]
    if policy == "prohibited" and mode != "none":
        raise ValueError("coordinate_policy_prohibits_representation")
    if policy == "unknown_hold" and mode != "none":
        raise ValueError("coordinate_policy_hold")


def _semantic_checks(
    conn: sqlite3.Connection,
    batch_source_id: str,
    batch_source: dict[str, Any],
    record: dict[str, Any],
) -> None:
    kind = record["record_type"]
    if kind == "source_registry_entry":
        if record["source_id"] != batch_source_id:
            raise ValueError("source_registry_batch_source_mismatch")
        _retention_gate(record)
        return
    if kind == "provenance_record":
        if record["source_id"] != batch_source_id:
            raise ValueError("provenance_batch_source_mismatch")
        _coord_gate(batch_source, record["coordinate_representation"]["mode"])
        return
    if kind == "survey_effort":
        if _dt(record["ended_at"]) < _dt(record["started_at"]):
            raise ValueError("survey_ended_before_started")
        if record["observer_count"] != len(record["observer_pseudonyms"]):
            raise ValueError("observer_count_mismatch")
        return
    if kind == "lifecycle_site":
        provenance = _require(conn, "provenance_record", record["created_from_provenance_id"])
        provenance_source = _source(conn, provenance["source_id"])
        if provenance_source is None:
            raise ValueError("site_provenance_source_missing")
        location = record["location"]
        if location["latitude"] is not None or location["longitude"] is not None:
            raise ValueError("exact_site_coordinate_forbidden")
        _coord_gate(provenance_source, location["mode"])
        return
    if kind == "lifecycle_observation":
        site = _require(conn, "lifecycle_site", record["site_id"])
        survey = _require(conn, "survey_effort", record["survey_id"])
        _require(conn, "provenance_record", record["provenance_id"])
        if record["taxonomic_assertion_id"] is not None:
            _require(conn, "taxonomic_evidence", record["taxonomic_assertion_id"])
        when = _dt(record["observed_at"])
        if not (_dt(survey["started_at"]) <= when <= _dt(survey["ended_at"])):
            raise ValueError("observation_outside_survey_window")
        if site["review_state"] in {"rejected", "retracted", "superseded"}:
            raise ValueError("observation_bound_to_inactive_site")
        return
    if kind == "media_evidence":
        _require(conn, "lifecycle_observation", record["observation_id"])
        if record["derivative_of"] is not None:
            _require(conn, "media_evidence", record["derivative_of"])
        return
    if kind == "environmental_snapshot":
        observation = _require(conn, "lifecycle_observation", record["observation_id"])
        _require(conn, "environmental_evidence_sheet", record["predictor_id"])
        match = _require(conn, "temporal_match", record["temporal_match_id"])
        _require(conn, "provenance_record", record["provenance_id"])
        if _dt(match["biological_observed_at"]) != _dt(observation["observed_at"]):
            raise ValueError("environmental_temporal_match_observation_mismatch")
        return
    if kind == "lifecycle_transition":
        if record["from_observation_id"] == record["to_observation_id"]:
            raise ValueError("self_transition")
        before = _require(conn, "lifecycle_observation", record["from_observation_id"])
        after = _require(conn, "lifecycle_observation", record["to_observation_id"])
        if before["site_id"] != after["site_id"] or before["site_id"] != record["site_id"]:
            raise ValueError("transition_site_mismatch")
        if before["episode_id"] != after["episode_id"] or before["episode_id"] != record["episode_id"]:
            raise ValueError("transition_episode_mismatch")
        if _dt(after["observed_at"]) < _dt(before["observed_at"]):
            raise ValueError("transition_reverse_time")
        effective = _dt(record["effective_at"])
        if not (_dt(before["observed_at"]) <= effective <= _dt(after["observed_at"])):
            raise ValueError("transition_effective_time_outside_evidence_window")
        if record["supersedes_transition_id"] is not None:
            previous = _require(conn, "lifecycle_transition", record["supersedes_transition_id"])
            if previous["site_id"] != record["site_id"]:
                raise ValueError("transition_supersession_site_mismatch")
        return
    if kind == "temporal_match":
        if record["source_observed_at"] is not None:
            source_at = _dt(record["source_observed_at"])
            if record["temporal_role"] == "antecedent" and source_at > _dt(record["biological_observed_at"]):
                raise ValueError("antecedent_predictor_after_biological_observation")
        return
    if kind in {"taxonomic_evidence", "environmental_evidence_sheet"}:
        return
    raise ValueError(f"unsupported_record_type:{kind}")


def _event(
    conn: sqlite3.Connection,
    event_type: str,
    raw_record_id: str | None,
    basis: str,
    left: str | None = None,
    right: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    event_id = sha_text(
        "\x1f".join(["mycelial-event", event_type, left or "", right or "", raw_record_id or "", basis])
    )
    conn.execute(
        """INSERT OR IGNORE INTO record_events(
        event_id,event_type,left_record_id,right_record_id,raw_record_id,basis,details_json,appended_at
        ) VALUES(?,?,?,?,?,?,?,?)""",
        (event_id, event_type, left, right, raw_record_id, basis, canonical_json(details or {}), now_utc()),
    )


def _strict_json(text: str) -> Any:
    def reject_constant(value: str) -> Any:
        raise ValueError(f"invalid_json_constant:{value}")
    return json.loads(text, parse_constant=reject_constant)


def _jsonl_rows(payload: bytes) -> list[tuple[int, bytes, str]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("input_not_utf8") from exc
    rows: list[tuple[int, bytes, str]] = []
    offset = 0
    for index, line in enumerate(text.splitlines(keepends=True)):
        encoded = line.encode("utf-8")
        raw = payload[offset : offset + len(encoded)]
        offset += len(encoded)
        content = line.rstrip("\r\n")
        if content.strip():
            rows.append((index, raw, content))
    return rows


def _existing_receipt(conn: sqlite3.Connection, batch_id: str) -> IngestReceipt | None:
    row = conn.execute("SELECT payload_json FROM ingest_receipts WHERE batch_id=?", (batch_id,)).fetchone()
    return None if row is None else IngestReceipt(**json.loads(row["payload_json"]))


def _batch_source_candidate(records: list[dict[str, Any]], source_id: str) -> dict[str, Any] | None:
    matches = [
        record for record in records
        if record.get("record_type") == "source_registry_entry" and record.get("source_id") == source_id
    ]
    if len(matches) > 1:
        raise ValueError("multiple_source_registry_entries_in_batch")
    return matches[0] if matches else None


def _review_bucket(record: dict[str, Any]) -> Literal["accepted", "review_queue"]:
    return "review_queue" if record.get("review_state") in {"needs_review", "admitted_design_candidate"} else "accepted"


def ingest_jsonl_batch(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    batch_id: str,
    payload: bytes,
) -> IngestReceipt:
    if not source_id.strip() or not batch_id.strip():
        raise ValueError("missing_source_or_batch_id")
    digest = sha_bytes(payload)
    prior = _existing_receipt(conn, batch_id)
    if prior is not None:
        raw = conn.execute(
            "SELECT source_id,input_sha256 FROM raw_batches WHERE batch_id=?", (batch_id,)
        ).fetchone()
        if raw is None or raw["source_id"] != source_id or raw["input_sha256"] != digest:
            raise ValueError("batch_id_conflict")
        return prior

    rows = _jsonl_rows(payload)
    parsed: list[dict[str, Any] | None] = []
    parse_errors: dict[int, str] = {}
    for index, _raw, text in rows:
        try:
            value = _strict_json(text)
            if not isinstance(value, dict):
                raise ValueError("row_not_object")
            _finite(value)
        except (json.JSONDecodeError, ValueError) as exc:
            parsed.append(None)
            parse_errors[index] = str(exc)
        else:
            parsed.append(value)

    records = [record for record in parsed if record is not None]
    source_candidate = _batch_source_candidate(records, source_id)
    if source_candidate is not None:
        errors = validate_record(source_candidate)
        if errors:
            raise ValueError({"error": "invalid_source_registry_entry", "violations": errors})
    source = _source(conn, source_id) or source_candidate
    if source is None:
        raise ValueError("source_registry_required_before_or_with_batch")
    _retention_gate(source)

    started = now_utc()
    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT INTO raw_batches(batch_id,source_id,input_sha256,payload_bytes,appended_at) VALUES(?,?,?,?,?)",
            (batch_id, source_id, digest, payload, now_utc()),
        )
        attempted = accepted = rejected = review_queue = exact_replays = duplicate_candidates = 0
        iterator = iter(parsed)

        for row_index, raw_bytes, raw_text in rows:
            attempted += 1
            raw_id = sha_text(f"raw\x1f{batch_id}\x1f{row_index}\x1f{sha_bytes(raw_bytes)}")
            record = next(iterator)
            conn.execute(
                """INSERT INTO raw_records(
                raw_record_id,batch_id,row_index,raw_sha256,raw_text,parse_status,source_record_id,appended_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    raw_id,
                    batch_id,
                    row_index,
                    sha_bytes(raw_bytes),
                    raw_text,
                    "parsed" if record is not None else "rejected_parse",
                    record.get("source_record_id") if isinstance(record, dict) else None,
                    now_utc(),
                ),
            )
            if record is None:
                rejected += 1
                _event(conn, "rejected", raw_id, "json_parse_or_nonfinite_failure",
                       details={"error": parse_errors.get(row_index, "parse_failure")})
                continue

            errors = validate_record(record)
            if errors:
                rejected += 1
                _event(conn, "rejected", raw_id, "schema_invalid", details={"violations": errors})
                continue

            kind = record["record_type"]
            stable_id = _stable_id(record)
            normalized_json = canonical_json(record)
            normalized_id = sha_text(f"normalized\x1f{raw_id}")
            conn.execute(
                """INSERT INTO normalized_records(
                normalized_record_id,raw_record_id,record_type,stable_id,payload_sha256,payload_json,appended_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (normalized_id, raw_id, kind, stable_id, sha_text(normalized_json), normalized_json, now_utc()),
            )

            governing_source = record if kind == "source_registry_entry" else (_source(conn, source_id) or source_candidate)
            if governing_source is None:
                rejected += 1
                _event(conn, "rejected", raw_id, "source_registry_missing")
                continue
            try:
                _semantic_checks(conn, source_id, governing_source, record)
            except ValueError as exc:
                rejected += 1
                _event(conn, "rejected", raw_id, "semantic_or_binding_failure", details={"error": str(exc)})
                continue

            payload_sha = sha_text(canonical_json(record))
            canonical_id = _canonical_id(kind, stable_id)
            existing = _load(conn, kind, stable_id)
            if existing is not None:
                existing_row, _ = existing
                if existing_row["payload_sha256"] == payload_sha:
                    exact_replays += 1
                    _event(conn, "exact_replay", raw_id, "same_type_stable_id_payload",
                           left=existing_row["canonical_record_id"], right=canonical_id)
                else:
                    rejected += 1
                    _event(conn, "rejected", raw_id, "stable_id_payload_conflict",
                           left=existing_row["canonical_record_id"], right=canonical_id,
                           details={"existing_sha256": existing_row["payload_sha256"], "incoming_sha256": payload_sha})
                continue

            review_state = record.get("review_state")
            conn.execute(
                """INSERT INTO canonical_records(
                canonical_record_id,record_type,stable_id,source_id,normalized_record_id,
                payload_sha256,payload_json,evidence_review_state,active,appended_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    canonical_id, kind, stable_id, source_id, normalized_id, payload_sha,
                    canonical_json(record), review_state,
                    int(review_state not in {"rejected", "retracted", "superseded"}), now_utc(),
                ),
            )
            if _review_bucket(record) == "review_queue":
                review_queue += 1
                _event(conn, "review_queue", raw_id, f"evidence_review_state:{review_state}", left=canonical_id)
            else:
                accepted += 1

            if kind == "provenance_record":
                duplicate_key = record["duplicate_candidate_key"]
                for candidate in conn.execute(
                    "SELECT canonical_record_id,payload_json FROM canonical_records "
                    "WHERE record_type='provenance_record' AND canonical_record_id<>? ORDER BY canonical_record_id",
                    (canonical_id,),
                ).fetchall():
                    other = json.loads(candidate["payload_json"])
                    if other.get("duplicate_candidate_key") == duplicate_key and other.get("source_id") != record["source_id"]:
                        duplicate_candidates += 1
                        left, right = sorted((candidate["canonical_record_id"], canonical_id))
                        _event(conn, "duplicate_candidate", raw_id,
                               "matching_cross_source_duplicate_candidate_key", left=left, right=right)

        receipt = IngestReceipt(
            receipt_id=sha_text(f"receipt\x1f{source_id}\x1f{batch_id}\x1f{digest}"),
            source_id=source_id,
            batch_id=batch_id,
            input_sha256=digest,
            started_at=started,
            completed_at=now_utc(),
            status="rejected" if attempted == 0 else ("complete" if rejected == 0 else "partial"),
            attempted=attempted,
            accepted=accepted,
            rejected=rejected,
            review_queue=review_queue,
            exact_replays=exact_replays,
            duplicate_candidates=duplicate_candidates,
        )
        receipt.assert_closed()
        conn.execute(
            "INSERT INTO ingest_receipts(receipt_id,batch_id,payload_json,appended_at) VALUES(?,?,?,?)",
            (receipt.receipt_id, batch_id, canonical_json(asdict(receipt)), now_utc()),
        )
        conn.commit()
        return receipt
    except Exception:
        conn.rollback()
        raise


def raw_batch_bytes(conn: sqlite3.Connection, batch_id: str) -> bytes:
    row = conn.execute("SELECT payload_bytes FROM raw_batches WHERE batch_id=?", (batch_id,)).fetchone()
    if row is None:
        raise KeyError(batch_id)
    return bytes(row["payload_bytes"])


def canonical_payload(conn: sqlite3.Connection, record_type: str, stable_id: str) -> dict[str, Any]:
    item = _load(conn, record_type, stable_id)
    if item is None:
        raise KeyError(f"{record_type}:{stable_id}")
    return item[1]


def training_candidate_only(record: dict[str, Any]) -> bool:
    """Conservative pre-Ballot-B filter; this never authorizes model fitting."""
    if record.get("review_state") not in {None, "admitted"}:
        return False
    return record.get("contradiction_state") not in {"potential", "confirmed"}
