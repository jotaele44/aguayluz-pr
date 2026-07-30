"""Phase 3 append-only incident operations acceptance tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.backend.monitoring_incident_ledger import (
    append_event,
    escalation_candidates,
    federation_delta,
    notification_outbox,
    read_events,
    replay,
    verify_chain,
)


def test_append_only_chain_and_replay_equal_materialized_state(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    append_event("MON-1", "opened", "system", "phase2 materialization", {"evidence": {"value": 9}}, ledger, "2026-07-30T10:00:00+00:00")
    append_event("MON-1", "acknowledged", "alice", "operator review", {}, ledger, "2026-07-30T10:05:00+00:00")
    append_event("MON-1", "assigned", "alice", "route to hydrology", {"assignee": "hydrology"}, ledger, "2026-07-30T10:06:00+00:00")
    events = read_events(ledger)
    assert verify_chain(events) is True
    assert replay(events) == replay(read_events(ledger))
    assert replay(events)["MON-1"]["status"] == "acknowledged"
    assert replay(events)["MON-1"]["assignee"] == "hydrology"
    assert replay(events)["MON-1"]["evidence_sha256"]


def test_operator_and_reason_provenance_fail_closed(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    append_event("MON-1", "opened", "system", "bootstrap", {}, ledger)
    with pytest.raises(ValueError, match="operator_and_reason_required"):
        append_event("MON-1", "resolved", "", "", {}, ledger)


def test_hash_tampering_breaks_replay(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    append_event("MON-1", "opened", "system", "bootstrap", {}, ledger)
    event = json.loads(ledger.read_text(encoding="utf-8"))
    event["reason"] = "tampered"
    ledger.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash_mismatch"):
        replay(read_events(ledger))


def test_resolve_reopen_threshold_migration_are_replayable(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    append_event("MON-1", "opened", "system", "bootstrap", {}, ledger)
    append_event("MON-1", "resolved", "alice", "recovered", {}, ledger)
    append_event("MON-1", "reopened", "bob", "new certified breach", {}, ledger)
    append_event("MON-1", "threshold_migrated", "bob", "approved table update", {"threshold_version": "v2"}, ledger)
    state = replay(read_events(ledger))["MON-1"]
    assert state["status"] == "active"
    assert state["threshold_version"] == "v2"
    assert state["timeline_count"] == 4


def test_federation_delta_cursor_is_append_only(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    first = append_event("MON-1", "opened", "system", "bootstrap", {}, ledger)
    second = append_event("MON-1", "acknowledged", "alice", "review", {}, ledger)
    full = federation_delta(read_events(ledger))
    delta = federation_delta(read_events(ledger), first["event_id"])
    assert full["append_only"] is True
    assert full["event_count"] == 2
    assert delta["event_count"] == 1
    assert delta["items"][0]["event_id"] == second["event_id"]
    with pytest.raises(ValueError, match="unknown_delta_cursor"):
        federation_delta(read_events(ledger), "missing")


def test_notification_delivery_is_disabled_by_default(tmp_path: Path):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"notification_outbox": {"enabled": False}}), encoding="utf-8")
    body = notification_outbox({"MON-1": {"incident_id": "MON-1", "status": "active"}}, policy)
    assert body == {"enabled": False, "delivery_enabled": False, "queued": []}


def test_escalation_is_maintenance_aware(tmp_path: Path, monkeypatch):
    from server.backend import monitoring_incident_ledger as ledger_module
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"escalation": {"unacknowledged_hours": 2, "level": 1}}), encoding="utf-8")
    monkeypatch.setattr(ledger_module, "maintenance_active", lambda incident, now=None: {"window": "active"})
    states = {"MON-1": {"incident_id": "MON-1", "status": "active", "last_event_at": "2026-07-30T10:00:00+00:00"}}
    now = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)
    assert escalation_candidates(states, now, policy) == []


def test_phase3_api_and_gui_contracts_are_wired():
    app_source = Path("server/backend/app.py").read_text(encoding="utf-8")
    gui_source = Path("dashboard/src/components/IncidentOperationsConsole.jsx").read_text(encoding="utf-8")
    for route in (
        "/monitoring/incidents/bootstrap",
        "/monitoring/incidents/{incident_id}/transitions",
        "/monitoring/incidents/{incident_id}/timeline",
        "/monitoring/incidents/notification-outbox",
        "/export/federation/monitoring-incident-events.json",
    ):
        assert route in app_source
    assert "Depends(legacy._require_key)" in app_source
    assert "Live notification delivery disabled" in gui_source
    assert "replay_equals_materialized_state" in gui_source
