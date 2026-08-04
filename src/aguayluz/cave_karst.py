"""Evidence-auditable cave and karst monitoring primitives for AguaYLuz-PR."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from . import DATA_DIR, SCHEMAS_DIR

ASSET_SCHEMA = "cave_karst_asset.schema.json"
SOURCE_SCHEMA = "cave_karst_source.schema.json"
EDGE_SCHEMA = "cave_karst_edge.schema.json"
EVENT_SCHEMA = "cave_karst_status_event.schema.json"
OBSERVATION_SCHEMA = "cave_karst_observation.schema.json"

STATUS_VALUES = {
    "open",
    "closed",
    "partially_open",
    "restricted",
    "maintenance",
    "unknown",
}
ALLOWED_STATUS_TRANSITIONS = {
    "unknown": STATUS_VALUES,
    "open": {"closed", "partially_open", "restricted", "maintenance", "unknown"},
    "closed": {"open", "partially_open", "restricted", "maintenance", "unknown"},
    "partially_open": {"open", "closed", "restricted", "maintenance", "unknown"},
    "restricted": {"open", "closed", "partially_open", "maintenance", "unknown"},
    "maintenance": {"open", "closed", "partially_open", "restricted", "unknown"},
}
PUBLIC_OPERATIONAL_KINDS = {"park", "cave", "access_infrastructure"}
STATUS_EVENT_TYPES = {
    "status_transition",
    "status_observation",
    "closure_notice",
    "reopening_notice",
    "restriction_notice",
    "maintenance_update",
}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _canonical_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_record_hash(record: dict[str, Any]) -> str:
    """Hash an event deterministically, excluding its stored record hash."""
    payload = dict(record)
    payload.pop("record_hash", None)
    digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
    return f"sha256:{digest}"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load nonblank JSONL rows; a missing optional registry file is empty."""
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _schema_validator(schema_name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_records(records: Iterable[dict[str, Any]], schema_name: str) -> list[str]:
    """Return stable schema diagnostics without mutating input records."""
    validator = _schema_validator(schema_name)
    errors: list[str] = []
    for index, record in enumerate(records):
        ordered = sorted(validator.iter_errors(record), key=lambda item: list(item.path))
        for error in ordered:
            location = ".".join(str(part) for part in error.path) or "<root>"
            errors.append(f"{schema_name}[{index}].{location}: {error.message}")
    return errors


def verify_event_chain(events: Iterable[dict[str, Any]]) -> list[str]:
    """Verify schema, ordering, transitions, intervals, and hash-chain integrity."""
    rows = list(events)
    errors = validate_records(rows, EVENT_SCHEMA)
    previous_hash: str | None = None
    previous_recorded_at: datetime | None = None

    for index, event in enumerate(rows):
        if event.get("previous_hash") != previous_hash:
            errors.append(
                f"event[{index}] previous_hash mismatch: expected {previous_hash!r}, "
                f"got {event.get('previous_hash')!r}"
            )
        expected_hash = compute_record_hash(event)
        if event.get("record_hash") != expected_hash:
            errors.append(
                f"event[{index}] record_hash mismatch: expected {expected_hash}, "
                f"got {event.get('record_hash')}"
            )

        recorded_at = _parse_dt(event.get("recorded_at"))
        if previous_recorded_at and recorded_at and recorded_at < previous_recorded_at:
            errors.append(f"event[{index}] recorded_at is not append-only ordered")
        previous_recorded_at = recorded_at or previous_recorded_at
        previous_hash = event.get("record_hash")

        if event.get("event_type") == "status_transition":
            before = event.get("from_status")
            after = event.get("to_status")
            if before is None:
                errors.append(f"event[{index}] status_transition requires from_status")
            elif after not in ALLOWED_STATUS_TRANSITIONS.get(before, set()):
                errors.append(f"event[{index}] disallowed transition {before}->{after}")

        effective_from = _parse_dt(event.get("effective_from"))
        effective_to = _parse_dt(event.get("effective_to"))
        if effective_from and effective_to and effective_to < effective_from:
            errors.append(f"event[{index}] effective_to precedes effective_from")
    return errors


def _active_status_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted = [
        event
        for event in events
        if event.get("review_status") == "accepted"
        and event.get("event_type") in STATUS_EVENT_TYPES
    ]
    superseded = {
        event["supersedes_event_id"]
        for event in accepted
        if event.get("supersedes_event_id")
    }
    return [event for event in accepted if event.get("event_id") not in superseded]


def detect_status_contradictions(
    events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find overlapping accepted, non-superseded assertions with different states."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in _active_status_events(events):
        grouped[event["asset_id"]].append(event)

    contradictions: list[dict[str, Any]] = []
    distant_past = datetime.min.replace(tzinfo=timezone.utc)
    distant_future = datetime.max.replace(tzinfo=timezone.utc)
    for asset_id, rows in grouped.items():
        rows.sort(
            key=lambda event: (
                _parse_dt(event.get("effective_from"))
                or _parse_dt(event.get("observed_at"))
                or distant_past,
                event["event_id"],
            )
        )
        for left_index, left in enumerate(rows):
            left_start = (
                _parse_dt(left.get("effective_from"))
                or _parse_dt(left.get("observed_at"))
                or distant_past
            )
            left_end = _parse_dt(left.get("effective_to")) or distant_future
            for right in rows[left_index + 1 :]:
                right_start = (
                    _parse_dt(right.get("effective_from"))
                    or _parse_dt(right.get("observed_at"))
                    or distant_past
                )
                right_end = _parse_dt(right.get("effective_to")) or distant_future
                if max(left_start, right_start) > min(left_end, right_end):
                    continue
                if left.get("to_status") == right.get("to_status"):
                    continue
                contradictions.append(
                    {
                        "asset_id": asset_id,
                        "left_event_id": left["event_id"],
                        "right_event_id": right["event_id"],
                        "left_status": left["to_status"],
                        "right_status": right["to_status"],
                    }
                )
    return contradictions


def materialize_status(
    assets: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Materialize current state without altering append-only source records."""
    cutoff = as_of or datetime.now(timezone.utc)
    applicable: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in _active_status_events(list(events)):
        effective_at = _parse_dt(event.get("effective_from")) or _parse_dt(
            event.get("observed_at")
        )
        effective_to = _parse_dt(event.get("effective_to"))
        if effective_at and effective_at <= cutoff and (not effective_to or cutoff <= effective_to):
            applicable[event["asset_id"]].append(event)

    materialized: list[dict[str, Any]] = []
    distant_past = datetime.min.replace(tzinfo=timezone.utc)
    for asset in assets:
        candidates = applicable.get(asset["asset_id"], [])
        candidates.sort(
            key=lambda event: (
                _parse_dt(event.get("effective_from"))
                or _parse_dt(event.get("observed_at"))
                or distant_past,
                _parse_dt(event.get("recorded_at")) or distant_past,
                event["event_id"],
            )
        )
        latest = candidates[-1] if candidates else None
        snapshot = dict(asset)
        snapshot["current_status"] = (
            latest["to_status"] if latest else asset["operational"]["status"]
        )
        snapshot["status_event_id"] = latest["event_id"] if latest else None
        snapshot["status_as_of"] = (
            latest.get("effective_from") or latest.get("observed_at")
            if latest
            else asset["operational"].get("status_as_of")
        )
        materialized.append(snapshot)
    return materialized


def build_alerts(
    assets: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    *,
    as_of: datetime | None = None,
    stale_after_days: int = 30,
) -> list[dict[str, Any]]:
    """Build deterministic access, freshness, flood-risk, and contradiction alerts."""
    cutoff = as_of or datetime.now(timezone.utc)
    event_rows = list(events)
    alerts: list[dict[str, Any]] = []
    for asset in materialize_status(assets, event_rows, as_of=cutoff):
        status = asset["current_status"]
        token = asset["asset_id"].removeprefix("AYL_KARST_")
        if asset["asset_kind"] in PUBLIC_OPERATIONAL_KINDS and status in {
            "closed",
            "partially_open",
            "restricted",
            "maintenance",
        }:
            alerts.append(
                {
                    "alert_id": f"AYL_KALERT_{token}_ACCESS",
                    "asset_id": asset["asset_id"],
                    "alert_type": "public_access_restriction",
                    "severity": 3 if status == "closed" else 2,
                    "state": "active",
                    "summary": f"{asset['canonical_name']} is {status.replace('_', ' ')}.",
                    "status_as_of": asset.get("status_as_of"),
                    "evidence_tier": asset["evidence_tier"],
                    "confidence": asset["confidence"],
                }
            )

        status_time = _parse_dt(asset.get("status_as_of"))
        if not status_time or (cutoff - status_time).days > stale_after_days:
            alerts.append(
                {
                    "alert_id": f"AYL_KALERT_{token}_STALE",
                    "asset_id": asset["asset_id"],
                    "alert_type": "stale_operational_status",
                    "severity": 2,
                    "state": "active",
                    "summary": f"{asset['canonical_name']} lacks a current operational-status observation.",
                    "status_as_of": asset.get("status_as_of"),
                    "evidence_tier": asset["evidence_tier"],
                    "confidence": min(asset["confidence"], 60),
                }
            )

        if asset["hydrologic"]["flood_sensitivity"] == "high" and status in {
            "open",
            "partially_open",
        }:
            alerts.append(
                {
                    "alert_id": f"AYL_KALERT_{token}_FLOOD",
                    "asset_id": asset["asset_id"],
                    "alert_type": "hydrologic_access_risk",
                    "severity": 4,
                    "state": "active",
                    "summary": f"{asset['canonical_name']} is accessible and has high flood sensitivity.",
                    "status_as_of": asset.get("status_as_of"),
                    "evidence_tier": asset["evidence_tier"],
                    "confidence": asset["confidence"],
                }
            )

    for conflict in detect_status_contradictions(event_rows):
        token = conflict["asset_id"].removeprefix("AYL_KARST_")
        alerts.append(
            {
                "alert_id": (
                    f"AYL_KALERT_{token}_CONTRADICTION_"
                    f"{conflict['left_event_id']}_{conflict['right_event_id']}"
                ),
                "asset_id": conflict["asset_id"],
                "alert_type": "status_contradiction",
                "severity": 3,
                "state": "active",
                "summary": (
                    f"Conflicting accepted status events: {conflict['left_status']} "
                    f"versus {conflict['right_status']}."
                ),
                "status_as_of": None,
                "evidence_tier": "T2",
                "confidence": 50,
            }
        )
    return sorted(alerts, key=lambda item: item["alert_id"])


def _duplicates(rows: list[dict[str, Any]], field: str) -> list[str]:
    values = [row.get(field) for row in rows]
    return [
        f"duplicate {field}: {value}"
        for value in sorted({value for value in values if values.count(value) > 1})
    ]


def validate_registry(
    assets: Iterable[dict[str, Any]],
    sources: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    observations: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Validate schemas, IDs, references, the event chain, and contradictions."""
    asset_rows = list(assets)
    source_rows = list(sources)
    edge_rows = list(edges)
    event_rows = list(events)
    observation_rows = list(observations)
    errors: list[str] = []

    for rows, schema in (
        (asset_rows, ASSET_SCHEMA),
        (source_rows, SOURCE_SCHEMA),
        (edge_rows, EDGE_SCHEMA),
        (event_rows, EVENT_SCHEMA),
        (observation_rows, OBSERVATION_SCHEMA),
    ):
        errors.extend(validate_records(rows, schema))
    errors.extend(verify_event_chain(event_rows))
    for rows, field in (
        (asset_rows, "asset_id"),
        (source_rows, "source_id"),
        (edge_rows, "edge_id"),
        (event_rows, "event_id"),
        (observation_rows, "observation_id"),
    ):
        errors.extend(_duplicates(rows, field))

    asset_ids = {row["asset_id"] for row in asset_rows}
    source_ids = {row["source_id"] for row in source_rows}
    for asset in asset_rows:
        parent = asset.get("parent_asset_id")
        if parent and parent not in asset_ids:
            errors.append(f"asset {asset['asset_id']} references missing parent {parent}")
        for source_ref in asset["source_refs"]:
            if source_ref not in source_ids:
                errors.append(f"asset {asset['asset_id']} references missing source {source_ref}")

    for edge in edge_rows:
        if edge["from_asset_id"] not in asset_ids:
            errors.append(f"edge {edge['edge_id']} references missing from_asset_id")
        if edge["to_node_type"] == "cave_asset" and edge["to_node_id"] not in asset_ids:
            errors.append(f"edge {edge['edge_id']} references missing cave asset")
        for source_ref in edge["source_refs"]:
            if source_ref not in source_ids:
                errors.append(f"edge {edge['edge_id']} references missing source {source_ref}")

    for event in event_rows:
        if event["asset_id"] not in asset_ids:
            errors.append(f"event {event['event_id']} references missing asset")
        if event["source_ref"] not in source_ids:
            errors.append(f"event {event['event_id']} references missing source")

    for observation in observation_rows:
        if observation["asset_id"] not in asset_ids:
            errors.append(f"observation {observation['observation_id']} references missing asset")
        if observation["source_ref"] not in source_ids:
            errors.append(f"observation {observation['observation_id']} references missing source")

    contradictions = detect_status_contradictions(event_rows)
    return {
        "ok": not errors,
        "asset_count": len(asset_rows),
        "source_count": len(source_rows),
        "edge_count": len(edge_rows),
        "event_count": len(event_rows),
        "observation_count": len(observation_rows),
        "contradiction_count": len(contradictions),
        "errors": sorted(set(errors)),
        "contradictions": contradictions,
    }


def load_default_registry(data_dir: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """Load the canonical cave-and-karst registry from the package data directory."""
    base = data_dir or DATA_DIR
    return {
        "assets": load_jsonl(base / "cave_karst_assets.jsonl"),
        "sources": load_jsonl(base / "cave_karst_sources.jsonl"),
        "edges": load_jsonl(base / "cave_karst_edges.jsonl"),
        "events": load_jsonl(base / "cave_karst_status_events.jsonl"),
        "observations": load_jsonl(base / "cave_karst_observations.jsonl"),
    }
