"""Phase 1 Ballot A research-ingest ledger for fungal lifecycle evidence.

No API/GUI surface. No calibration, prediction, suitability, connectivity,
notifications, coordinate disclosure, infrastructure inference, or controls.
RAW, NORMALIZED, and CANONICAL manifestations remain separate.
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
_PRIORITY = {
    "source_registry_entry": 0,
    "provenance_record": 10,
    "taxonomic_evidence": 10,
    "survey_effort": 10,
    "temporal_match": 10,
    "environmental_evidence_sheet": 10,
    "lifecycle_site": 20,
    "lifecycle_observation": 30,
    "media_evidence": 40,
    "environmental_snapshot": 40,
    "lifecycle_transition": 50,
}
_TABLES = (
    "raw_batches", "raw_records", "normalized_records",
    "canonical_records", "record_events", "ingest_receipts",
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
        total = self.accepted + self.rejected + self.review_queue + self.exact_replays
        if self.attempted != total:
            raise ValueError("receipt_accounting_mismatch")


DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS raw_batches(
 batch_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,input_sha256 TEXT NOT NULL,
 payload_bytes BLOB NOT NULL,appended_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS raw_records(
 raw_record_id TEXT PRIMARY KEY,batch_id TEXT NOT NULL REFERENCES raw_batches(batch_id),
 row_index INTEGER NOT NULL,raw_sha256 TEXT NOT NULL,raw_text TEXT NOT NULL,
 parse_status TEXT NOT NULL,source_record_id TEXT,appended_at TEXT NOT NULL,
 UNIQUE(batch_id,row_index));
CREATE TABLE IF NOT EXISTS normalized_records(
 normalized_record_id TEXT PRIMARY KEY,
 raw_record_id TEXT NOT NULL UNIQUE REFERENCES raw_records(raw_record_id),
 record_type TEXT NOT NULL,stable_id TEXT NOT NULL,payload_sha256 TEXT NOT NULL,
 payload_json TEXT NOT NULL,appended_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS canonical_records(
 canonical_record_id TEXT PRIMARY KEY,record_type TEXT NOT NULL,stable_id TEXT NOT NULL,
 source_id TEXT NOT NULL,normalized_record_id TEXT NOT NULL REFERENCES normalized_records(normalized_record_id),
 payload_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,evidence_review_state TEXT,
 active INTEGER NOT NULL CHECK(active IN(0,1)),appended_at TEXT NOT NULL,
 UNIQUE(record_type,stable_id));
CREATE TABLE IF NOT EXISTS record_events(
 event_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,left_record_id TEXT,right_record_id TEXT,
 raw_record_id TEXT REFERENCES raw_records(raw_record_id),basis TEXT NOT NULL,
 details_json TEXT NOT NULL,appended_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ingest_receipts(
 receipt_id TEXT PRIMARY KEY,batch_id TEXT NOT NULL UNIQUE REFERENCES raw_batches(batch_id),
 payload_json TEXT NOT NULL,appended_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_myc_type_id ON canonical_records(record_type,stable_id);
CREATE INDEX IF NOT EXISTS idx_myc_source ON canonical_records(source_id);
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


def initialize_database(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    for table in _TABLES:
        conn.executescript(
            f"""CREATE TRIGGER IF NOT EXISTS deny_update_{table}
            BEFORE UPDATE ON {table} BEGIN
              SELECT RAISE(ABORT,'append_only:{table}:update'); END;
            CREATE TRIGGER IF NOT EXISTS deny_delete_{table}
            BEFORE DELETE ON {table} BEGIN
              SELECT RAISE(ABORT,'append_only:{table}:delete'); END;"""
        )
    conn.commit()
    return conn


@cache
def _validator(record_type: str) -> Draft202012Validator:
    name = _SCHEMA_FILES.get(record_type)
    if name is None:
        raise ValueError(f"unsupported_record_type:{record_type}")
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
    kind = record.get("record_type")
    if not isinstance(kind, str):
        return ["$.record_type: missing or non-string"]
    if record.get("schema_version") != SCHEMA_VERSION:
        return [f"$.schema_version: expected {SCHEMA_VERSION}"]
    try:
        _finite(record)
        errors = sorted(
            _validator(kind).iter_errors(record),
            key=lambda error: list(error.absolute_path),
        )
    except ValueError as exc:
        return [str(exc)]
    return [f"{error.json_path}: {error.message}" for error in errors]


def _stable_id(record: dict[str, Any]) -> str:
    kind = record["record_type"]
    field = _ID_FIELDS.get(kind)
    if field is None:
        raise ValueError(f"unsupported_record_type:{kind}")
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing_stable_id:{kind}:{field}")
    return value


def _canonical_id(kind: str, stable_id: str) -> str:
    return sha_text(f"mycelial-phase1\x1f{kind}\x1f{stable_id}")


def _load(
    conn: sqlite3.Connection, kind: str, stable_id: str
) -> tuple[sqlite3.Row, dict[str, Any]] | None:
    row = conn.execute(
        "SELECT * FROM canonical_records WHERE record_type=? AND stable_id=?",
        (kind, stable_id),
    ).fetchone()
    return None if row is None else (row, json.loads(row["payload_json"]))


def _require(conn: sqlite3.Connection, kind: str, stable_id: str) -> dict[str, Any]:
    item = _load(conn, kind, stable_id)
    if item is None:
        raise ValueError(f"missing_binding:{kind}:{stable_id}")
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
    elif kind == "provenance_record":
        if record["source_id"] != batch_source_id:
            raise ValueError("provenance_batch_source_mismatch")
        _coord_gate(batch_source, record["coordinate_representation"]["mode"])
    elif kind == "survey_effort":
        if _dt(record["ended_at"]) < _dt(record["started_at"]):
            raise ValueError("survey_ended_before_started")
        if record["observer_count"] != len(record["observer_pseudonyms"]):
            raise ValueError("observer_count_mismatch")
    elif kind == "lifecycle_site":
        provenance = _require(
            conn, "provenance_record", record["created_from_provenance_id"]
        )
        source = _source(conn, provenance["source_id"])
        if source is None:
            raise ValueError("site_provenance_source_missing")
        location = record["location"]
        if location["latitude"] is not None or location["longitude"] is not None:
            raise ValueError("exact_site_coordinate_forbidden")
        _coord_gate(source, location["mode"])
    elif kind == "lifecycle_observation":
        site = _require(conn, "lifecycle_site", record["site_id"])
        survey = _require(conn, "survey_effort", record["survey_id"])
        _require(conn, "provenance_record", record["provenance_id"])
        taxon = record["taxonomic_assertion_id"]
        if taxon is not None:
            _require(conn, "taxonomic_evidence", taxon)
        when = _dt(record["observed_at"])
        if not (_dt(survey["started_at"]) <= when <= _dt(survey["ended_at"])):
            raise ValueError("observation_outside_survey_window")
        if site["review_state"] in {"rejected", "retracted", "superseded"}:
            raise ValueError("observation_bound_to_inactive_site")
    elif kind == "media_evidence":
        _require(conn, "lifecycle_observation", record["observation_id"])
        if record["derivative_of"] is not None:
            _require(conn, "media_evidence", record["derivative_of"])
    elif kind == "environmental_snapshot":
        observation = _require(
            conn, "lifecycle_observation", record["observation_id"]
        )
        _require(conn, "environmental_evidence_sheet", record["predictor_id"])
        match = _require(conn, "temporal_match", record["temporal_match_id"])
        _require(conn, "provenance_record", record["provenance_id"])
        if _dt(match["biological_observed_at"]) != _dt(observation["observed_at"]):
            raise ValueError("environmental_temporal_match_observation_mismatch")
    elif kind == "lifecycle_transition":
        before_id = record["from_observation_id"]
        after_id = record["to_observation_id"]
        if before_id == after_id:
            raise ValueError("self_transition")
        before = _require(conn, "lifecycle_observation", before_id)
        after = _require(conn, "lifecycle_observation", after_id)
        if before["site_id"] != after["site_id"] or before["site_id"] != record["site_id"]:
            raise ValueError("transition_site_mismatch")
        if (
            before["episode_id"] != after["episode_id"]
            or before["episode_id"] != record["episode_id"]
        ):
            raise ValueError("transition_episode_mismatch")
        before_at, after_at = _dt(before["observed_at"]), _dt(after["observed_at"])
        if after_at < before_at:
            raise ValueError("transition_reverse_time")
        if not (before_at <= _dt(record["effective_at"]) <= after_at):
            raise ValueError("transition_effective_time_outside_evidence_window")
        if record["supersedes_transition_id"] is not None:
            previous = _require(
                conn, "lifecycle_transition", record["supersedes_transition_id"]
            )
            if previous["site_id"] != record["site_id"]:
                raise ValueError("transition_supersession_site_mismatch")
    elif kind == "temporal_match":
        if record["source_observed_at"] is not None:
            source_at = _dt(record["source_observed_at"])
            biological_at = _dt(record["biological_observed_at"])
            if record["temporal_role"] == "antecedent" and source_at > biological_at:
                raise ValueError("antecedent_predictor_after_biological_observation")
    elif kind not in {"taxonomic_evidence", "environmental_evidence_sheet"}:
        raise ValueError(f"unsupported_record_type:{kind}")


def _event(
    conn: sqlite3.Connection,
    event_type: str,
    raw_id: str | None,
    basis: str,
    *,
    left: str | None = None,
    right: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    event_id = sha_text(
        "\x1f".join(
            ["mycelial-event", event_type, left or "", right or "", raw_id or "", basis]
        )
    )
    conn.execute(
        """INSERT OR IGNORE INTO record_events(
        event_id,event_type,left_record_id,right_record_id,raw_record_id,
        basis,details_json,appended_at) VALUES(?,?,?,?,?,?,?,?)""",
        (
            event_id, event_type, left, right, raw_id, basis,
            canonical_json(details or {}), now_utc(),
        ),
    )


def _strict_json(text: str) -> Any:
    def reject(value: str) -> Any:
        raise ValueError(f"invalid_json_constant:{value}")

    return json.loads(text, parse_constant=reject)


def _rows(payload: bytes) -> list[tuple[int, bytes, str]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("input_not_utf8") from exc
    output: list[tuple[int, bytes, str]] = []
    offset = 0
    for index, line in enumerate(text.splitlines(keepends=True)):
        raw = payload[offset : offset + len(line.encode("utf-8"))]
        offset += len(raw)
        content = line.rstrip("\r\n")
        if content.strip():
            output.append((index, raw, content))
    return output


def _prior(conn: sqlite3.Connection, batch_id: str) -> IngestReceipt | None:
    row = conn.execute(
        "SELECT payload_json FROM ingest_receipts WHERE batch_id=?", (batch_id,)
    ).fetchone()
    return None if row is None else IngestReceipt(**json.loads(row["payload_json"]))


def _source_candidate(
    records: list[dict[str, Any]], source_id: str
) -> dict[str, Any] | None:
    matches = [
        record
        for record in records
        if record.get("record_type") == "source_registry_entry"
        and record.get("source_id") == source_id
    ]
    if len(matches) > 1:
        raise ValueError("multiple_source_registry_entries_in_batch")
    return matches[0] if matches else None


def _review_queue(record: dict[str, Any]) -> bool:
    return record.get("review_state") in {"needs_review", "admitted_design_candidate"}


def ingest_jsonl_batch(
    conn: sqlite3.Connection, *, source_id: str, batch_id: str, payload: bytes
) -> IngestReceipt:
    if not source_id.strip() or not batch_id.strip():
        raise ValueError("missing_source_or_batch_id")
    input_sha = sha_bytes(payload)
    prior = _prior(conn, batch_id)
    if prior is not None:
        row = conn.execute(
            "SELECT source_id,input_sha256 FROM raw_batches WHERE batch_id=?", (batch_id,)
        ).fetchone()
        if row is None or row["source_id"] != source_id or row["input_sha256"] != input_sha:
            raise ValueError("batch_id_conflict")
        return prior

    source_rows = _rows(payload)
    parsed: list[dict[str, Any] | None] = []
    parse_errors: dict[int, str] = {}
    for index, _raw, text in source_rows:
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

    parsed_records = [record for record in parsed if record is not None]
    candidate = _source_candidate(parsed_records, source_id)
    if candidate is not None:
        errors = validate_record(candidate)
        if errors:
            raise ValueError(
                {"error": "invalid_source_registry_entry", "violations": errors}
            )
    source = _source(conn, source_id) or candidate
    if source is None:
        raise ValueError("source_registry_required_before_or_with_batch")
    _retention_gate(source)

    started = now_utc()
    conn.execute("BEGIN")
    try:
        conn.execute(
            """INSERT INTO raw_batches(
            batch_id,source_id,input_sha256,payload_bytes,appended_at)
            VALUES(?,?,?,?,?)""",
            (batch_id, source_id, input_sha, payload, now_utc()),
        )
        rejected = accepted = review = replays = duplicates = 0
        prepared: list[tuple[int, int, str, str, dict[str, Any]]] = []
        iterator = iter(parsed)

        for row_index, raw, text in source_rows:
            record = next(iterator)
            raw_id = sha_text(
                f"raw\x1f{batch_id}\x1f{row_index}\x1f{sha_bytes(raw)}"
            )
            conn.execute(
                """INSERT INTO raw_records(
                raw_record_id,batch_id,row_index,raw_sha256,raw_text,
                parse_status,source_record_id,appended_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (
                    raw_id, batch_id, row_index, sha_bytes(raw), text,
                    "parsed" if record is not None else "rejected_parse",
                    record.get("source_record_id") if isinstance(record, dict) else None,
                    now_utc(),
                ),
            )
            if record is None:
                rejected += 1
                _event(
                    conn, "rejected", raw_id, "json_parse_or_nonfinite_failure",
                    details={"error": parse_errors.get(row_index, "parse_failure")},
                )
                continue
            errors = validate_record(record)
            if errors:
                rejected += 1
                _event(
                    conn, "rejected", raw_id, "schema_invalid",
                    details={"violations": errors},
                )
                continue
            kind, stable_id = record["record_type"], _stable_id(record)
            normalized = canonical_json(record)
            normalized_id = sha_text(f"normalized\x1f{raw_id}")
            conn.execute(
                """INSERT INTO normalized_records(
                normalized_record_id,raw_record_id,record_type,stable_id,
                payload_sha256,payload_json,appended_at)
                VALUES(?,?,?,?,?,?,?)""",
                (
                    normalized_id, raw_id, kind, stable_id,
                    sha_text(normalized), normalized, now_utc(),
                ),
            )
            prepared.append((_PRIORITY[kind], row_index, raw_id, normalized_id, record))

        for _rank, _row, raw_id, normalized_id, record in sorted(prepared):
            kind, stable_id = record["record_type"], _stable_id(record)
            governing_source = (
                record if kind == "source_registry_entry"
                else (_source(conn, source_id) or candidate)
            )
            if governing_source is None:
                rejected += 1
                _event(conn, "rejected", raw_id, "source_registry_missing")
                continue
            try:
                _semantic_checks(conn, source_id, governing_source, record)
            except ValueError as exc:
                rejected += 1
                _event(
                    conn, "rejected", raw_id, "semantic_or_binding_failure",
                    details={"error": str(exc)},
                )
                continue

            payload_json = canonical_json(record)
            payload_sha = sha_text(payload_json)
            canonical_id = _canonical_id(kind, stable_id)
            existing = _load(conn, kind, stable_id)
            if existing is not None:
                old, _payload = existing
                if old["payload_sha256"] == payload_sha:
                    replays += 1
                    _event(
                        conn, "exact_replay", raw_id, "same_type_stable_id_payload",
                        left=old["canonical_record_id"], right=canonical_id,
                    )
                else:
                    rejected += 1
                    _event(
                        conn, "rejected", raw_id, "stable_id_payload_conflict",
                        left=old["canonical_record_id"], right=canonical_id,
                        details={
                            "existing_sha256": old["payload_sha256"],
                            "incoming_sha256": payload_sha,
                        },
                    )
                continue

            review_state = record.get("review_state")
            conn.execute(
                """INSERT INTO canonical_records(
                canonical_record_id,record_type,stable_id,source_id,
                normalized_record_id,payload_sha256,payload_json,
                evidence_review_state,active,appended_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    canonical_id, kind, stable_id, source_id, normalized_id,
                    payload_sha, payload_json, review_state,
                    int(review_state not in {"rejected", "retracted", "superseded"}),
                    now_utc(),
                ),
            )
            if _review_queue(record):
                review += 1
                _event(
                    conn, "review_queue", raw_id,
                    f"evidence_review_state:{review_state}", left=canonical_id,
                )
            else:
                accepted += 1

            if kind == "provenance_record":
                key = record["duplicate_candidate_key"]
                candidates = conn.execute(
                    """SELECT canonical_record_id,payload_json FROM canonical_records
                    WHERE record_type='provenance_record'
                    AND canonical_record_id<>? ORDER BY canonical_record_id""",
                    (canonical_id,),
                ).fetchall()
                for row in candidates:
                    other = json.loads(row["payload_json"])
                    if (
                        other.get("duplicate_candidate_key") == key
                        and other.get("source_id") != record["source_id"]
                    ):
                        duplicates += 1
                        left, right = sorted((row["canonical_record_id"], canonical_id))
                        _event(
                            conn, "duplicate_candidate", raw_id,
                            "matching_cross_source_duplicate_candidate_key",
                            left=left, right=right,
                        )

        attempted = len(source_rows)
        successful = accepted + review + replays
        status: Literal["complete", "partial", "rejected"]
        if rejected == 0:
            status = "complete"
        elif successful == 0:
            status = "rejected"
        else:
            status = "partial"
        receipt = IngestReceipt(
            receipt_id=sha_text(
                f"receipt\x1f{source_id}\x1f{batch_id}\x1f{input_sha}"
            ),
            source_id=source_id,
            batch_id=batch_id,
            input_sha256=input_sha,
            started_at=started,
            completed_at=now_utc(),
            status=status,
            attempted=attempted,
            accepted=accepted,
            rejected=rejected,
            review_queue=review,
            exact_replays=replays,
            duplicate_candidates=duplicates,
        )
        receipt.assert_closed()
        conn.execute(
            """INSERT INTO ingest_receipts(
            receipt_id,batch_id,payload_json,appended_at) VALUES(?,?,?,?)""",
            (receipt.receipt_id, batch_id, canonical_json(asdict(receipt)), now_utc()),
        )
        conn.commit()
        return receipt
    except Exception:
        conn.rollback()
        raise


def raw_batch_bytes(conn: sqlite3.Connection, batch_id: str) -> bytes:
    row = conn.execute(
        "SELECT payload_bytes FROM raw_batches WHERE batch_id=?", (batch_id,)
    ).fetchone()
    if row is None:
        raise KeyError(batch_id)
    return bytes(row["payload_bytes"])


def canonical_payload(
    conn: sqlite3.Connection, record_type: str, stable_id: str
) -> dict[str, Any]:
    item = _load(conn, record_type, stable_id)
    if item is None:
        raise KeyError(f"{record_type}:{stable_id}")
    return item[1]


def training_candidate_only(record: dict[str, Any]) -> bool:
    """Pre-Ballot-B exclusion helper; this never authorizes model fitting."""
    if record.get("review_state") not in {None, "admitted"}:
        return False
    return record.get("contradiction_state") not in {"potential", "confirmed"}
