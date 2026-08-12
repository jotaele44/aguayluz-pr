from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from aguayluz.cave_karst import (
    build_alerts,
    compute_record_hash,
    detect_status_contradictions,
    load_default_registry,
    materialize_status,
    validate_registry,
    verify_event_chain,
)

AS_OF = datetime(2026, 8, 4, 1, 0, tzinfo=timezone.utc)


def test_rio_camuy_pilot_registry_validates() -> None:
    registry = load_default_registry()
    report = validate_registry(**registry)
    assert report["ok"] is True
    assert report["asset_count"] == 4
    assert report["source_count"] == 4
    assert report["edge_count"] == 6
    assert report["event_count"] == 3
    assert report["observation_count"] == 2
    assert report["contradiction_count"] == 0
    assert report["errors"] == []


def test_current_camuy_status_supersedes_historical_reopening() -> None:
    registry = load_default_registry()
    snapshots = {row["asset_id"]: row for row in materialize_status(registry["assets"], registry["events"], as_of=AS_OF)}
    park = snapshots["AYL_KARST_CAMUY_PARK"]
    assert park["current_status"] == "closed"
    assert park["status_event_id"] == "AYL_KEVT_CAMUY_CLOSED_OBS_20260803"
    assert park["status_as_of"] == "2026-08-04T00:44:00Z"


def test_event_chain_detects_tampering() -> None:
    registry = load_default_registry()
    tampered = deepcopy(registry["events"])
    tampered[1]["reason"] = "tampered"
    assert any("record_hash mismatch" in error for error in verify_event_chain(tampered))


def test_event_chain_accepts_recomputed_append() -> None:
    registry = load_default_registry()
    appended = deepcopy(registry["events"])
    event = {
        "event_id": "AYL_KEVT_CAMUY_TEST_20260804",
        "asset_id": "AYL_KARST_CAMUY_PARK",
        "event_type": "status_observation",
        "observed_at": "2026-08-04T01:00:00Z",
        "effective_from": None,
        "effective_to": None,
        "from_status": "unknown",
        "to_status": "closed",
        "reason": "Deterministic test append.",
        "source_ref": "SRC_KARST_DPR_CLOSED_20260803",
        "evidence_tier": "T2",
        "confidence": 85,
        "review_status": "accepted",
        "supersedes_event_id": "AYL_KEVT_CAMUY_CLOSED_OBS_20260803",
        "recorded_at": "2026-08-04T01:00:01Z",
        "previous_hash": appended[-1]["record_hash"],
        "record_hash": "",
    }
    event["record_hash"] = compute_record_hash(event)
    appended.append(event)
    assert verify_event_chain(appended) == []


def test_conflicting_accepted_status_intervals_are_detected() -> None:
    registry = load_default_registry()
    events = deepcopy(registry["events"])
    conflicting = {
        "event_id": "AYL_KEVT_CAMUY_CONFLICT_20260804",
        "asset_id": "AYL_KARST_CAMUY_PARK",
        "event_type": "status_observation",
        "observed_at": "2026-08-04T00:44:00Z",
        "effective_from": None,
        "effective_to": None,
        "from_status": "unknown",
        "to_status": "open",
        "reason": "Synthetic contradiction test.",
        "source_ref": "SRC_KARST_CTPR_REOPEN_20210317",
        "evidence_tier": "T1",
        "confidence": 100,
        "review_status": "accepted",
        "supersedes_event_id": None,
        "recorded_at": "2026-08-04T01:00:02Z",
        "previous_hash": events[-1]["record_hash"],
        "record_hash": "",
    }
    conflicting["record_hash"] = compute_record_hash(conflicting)
    events.append(conflicting)
    contradictions = detect_status_contradictions(events)
    assert len(contradictions) == 1
    assert contradictions[0]["asset_id"] == "AYL_KARST_CAMUY_PARK"


def test_pilot_emits_access_alerts_but_not_unverified_repair_completion() -> None:
    registry = load_default_registry()
    alerts = build_alerts(registry["assets"], registry["events"], as_of=AS_OF)
    alert_types = {alert["alert_type"] for alert in alerts}
    assert "public_access_restriction" in alert_types
    assert "hydrologic_access_risk" not in alert_types
    procurement = next(observation for observation in registry["observations"] if observation["metric"] == "repair_procurement_status")
    assert procurement["value"] == "cancelled"
    assert "completion" in procurement["notes"].lower()


def test_pilot_discloses_no_exact_cave_coordinates() -> None:
    registry = load_default_registry()
    for asset in registry["assets"]:
        assert asset["location_disclosure"] == "public_generalized"
        assert asset["lat"] is None
        assert asset["lon"] is None


def test_edges_are_typed_and_do_not_invent_utility_links() -> None:
    registry = load_default_registry()
    assert all(edge["relation"] for edge in registry["edges"])
    assert all(asset["infrastructure"]["linked_utility_asset_ids"] == [] for asset in registry["assets"])
