"""Append-only Phase 3 monitoring incident operations and deterministic replay."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LEDGER_PATH = Path(__file__).resolve().parents[2] / "data" / "monitoring_incident_ledger.jsonl"
MAINTENANCE_PATH = Path(__file__).resolve().parents[2] / "config" / "monitoring_maintenance_windows.json"
POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "monitoring_phase3_operations.json"
ALLOWED_EVENTS = {"opened", "acknowledged", "assigned", "suppressed", "resolved", "reopened", "escalated", "threshold_migrated"}
OPERATOR_EVENTS = ALLOWED_EVENTS - {"opened", "escalated"}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_events(path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_event(event: dict[str, Any]) -> None:
    if event.get("event_type") not in ALLOWED_EVENTS:
        raise ValueError("unknown_incident_event")
    for key in ("event_id", "incident_id", "event_type", "occurred_at", "actor", "reason", "previous_hash", "event_hash"):
        if key not in event:
            raise ValueError(f"missing_event_field:{key}")
    material = {key: value for key, value in event.items() if key != "event_hash"}
    if event["event_hash"] != _sha(material):
        raise ValueError("incident_event_hash_mismatch")


def append_event(
    incident_id: str,
    event_type: str,
    actor: str,
    reason: str,
    payload: dict[str, Any] | None = None,
    path: Path = LEDGER_PATH,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    if event_type not in ALLOWED_EVENTS:
        raise ValueError("unknown_incident_event")
    if event_type in OPERATOR_EVENTS and (not actor.strip() or not reason.strip()):
        raise ValueError("operator_and_reason_required")
    events = read_events(path)
    previous_hash = events[-1]["event_hash"] if events else "GENESIS"
    body = {
        "incident_id": incident_id,
        "event_type": event_type,
        "occurred_at": occurred_at or _now(),
        "actor": actor,
        "reason": reason,
        "payload": payload or {},
        "previous_hash": previous_hash,
    }
    body["event_id"] = f"IE-{_sha(body)[:24]}"
    body["event_hash"] = _sha(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_canonical(body) + "\n")
    return body


def verify_chain(events: Iterable[dict[str, Any]]) -> bool:
    previous = "GENESIS"
    for event in events:
        validate_event(event)
        if event["previous_hash"] != previous:
            raise ValueError("incident_ledger_chain_break")
        previous = event["event_hash"]
    return True


def replay(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    verify_chain(events)
    state: dict[str, dict[str, Any]] = {}
    for event in events:
        item = state.setdefault(event["incident_id"], {
            "incident_id": event["incident_id"], "status": "unknown", "assignee": None,
            "acknowledged_by": None, "suppressed_until": None, "timeline_count": 0,
            "last_event_at": None, "threshold_version": None, "evidence_sha256": None,
            "escalation_level": 0,
        })
        kind, payload = event["event_type"], event.get("payload", {})
        if kind in {"opened", "reopened"}:
            item["status"] = "active"
        elif kind == "acknowledged":
            item["status"] = "acknowledged"
            item["acknowledged_by"] = event["actor"]
        elif kind == "assigned":
            item["assignee"] = payload.get("assignee")
        elif kind == "suppressed":
            item["status"] = "suppressed"
            item["suppressed_until"] = payload.get("until")
        elif kind == "resolved":
            item["status"] = "resolved"
        elif kind == "escalated":
            item["escalation_level"] = max(item["escalation_level"], int(payload.get("level", 1)))
        elif kind == "threshold_migrated":
            item["threshold_version"] = payload.get("threshold_version")
        if payload.get("evidence") is not None:
            item["evidence_sha256"] = _sha(payload["evidence"])
        item["timeline_count"] += 1
        item["last_event_at"] = event["occurred_at"]
        item["last_actor"] = event["actor"]
        item["last_reason"] = event["reason"]
    return state


def materialized_state(path: Path = LEDGER_PATH) -> dict[str, dict[str, Any]]:
    return replay(read_events(path))


def timeline(incident_id: str, path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    return [event for event in read_events(path) if event["incident_id"] == incident_id]


def load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def maintenance_active(incident: dict[str, Any], now: datetime | None = None, path: Path = MAINTENANCE_PATH) -> dict[str, Any] | None:
    now = now or datetime.now(timezone.utc)
    for window in load_json(path, {"windows": []}).get("windows", []):
        start = datetime.fromisoformat(window["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(window["end"].replace("Z", "+00:00"))
        if start <= now <= end and (window.get("incident_id") in (None, incident.get("incident_id"))):
            return window
    return None


def escalation_candidates(states: dict[str, dict[str, Any]], now: datetime | None = None, policy_path: Path = POLICY_PATH) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    policy = load_json(policy_path, {}).get("escalation", {"unacknowledged_hours": 2, "level": 1})
    cutoff = now - timedelta(hours=float(policy["unacknowledged_hours"]))
    result = []
    for item in states.values():
        if item["status"] != "active" or maintenance_active(item, now):
            continue
        last = datetime.fromisoformat(str(item["last_event_at"]).replace("Z", "+00:00"))
        if last <= cutoff:
            result.append({"incident_id": item["incident_id"], "level": policy["level"], "reason": "unacknowledged_timeout"})
    return result


def notification_outbox(states: dict[str, dict[str, Any]], policy_path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = load_json(policy_path, {})
    enabled = bool(policy.get("notification_outbox", {}).get("enabled", False))
    return {"enabled": enabled, "delivery_enabled": False, "queued": [] if not enabled else [
        {"incident_id": item["incident_id"], "status": item["status"]}
        for item in states.values() if item["status"] in {"active", "acknowledged"}
    ]}


def federation_delta(events: list[dict[str, Any]], cursor: str | None = None) -> dict[str, Any]:
    start = 0
    if cursor:
        indexes = [index for index, event in enumerate(events) if event["event_id"] == cursor]
        if not indexes:
            raise ValueError("unknown_delta_cursor")
        start = indexes[-1] + 1
    items = events[start:]
    return {
        "schema_version": "1.0.0",
        "contract": "aguayluz.monitoring.incident-events",
        "append_only": True,
        "cursor": items[-1]["event_id"] if items else cursor,
        "event_count": len(items),
        "items": items,
    }
