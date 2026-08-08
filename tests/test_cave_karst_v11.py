from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from server.backend.cave_karst_api import (
    RULESET_VERSION,
    evaluate_replay_sample,
    materialize_v11_status,
    public_asset_projection,
    validate_public_projection,
)

from aguayluz import SCHEMAS_DIR
from aguayluz.cave_karst import compute_record_hash, load_default_registry, validate_registry

AS_OF = datetime(2026, 8, 7, 22, 0, tzinfo=timezone.utc)
CANONICAL_CAMUY_EVENT_HASHES = [
    "sha256:1c06d82c8e2b2d933faf5ceac71a4d81b6069a65b870e6cc96c5656db6168bd6",
    "sha256:eff7b2ba62306a58d66f3ac87f736386d78a5dfcf48d6f7db72f491422986b24",
    "sha256:0e3f9c9bc2eb77630d966a337a22f95768a57c1e9e19970f41aceeee99069746",
]


def test_v11_pilot_registry_validates_without_rewriting_event_hashes() -> None:
    registry = load_default_registry()
    report = validate_registry(**registry)
    assert report["ok"] is True
    assert report["errors"] == []
    assert {item["schema_version"] for item in registry["assets"]} == {"1.1.0"}
    assert all(item["privacy_class"] == "P1_GENERALIZED" for item in registry["assets"])
    assert all(item["operational"]["conflict_hold"] is False for item in registry["assets"])
    assert [item["record_hash"] for item in registry["events"]] == CANONICAL_CAMUY_EVENT_HASHES


def test_v11_current_camuy_state_remains_closed_and_verified() -> None:
    registry = load_default_registry()
    snapshots = {
        item["asset_id"]: item
        for item in materialize_v11_status(
            registry["assets"], registry["events"], as_of=AS_OF
        )
    }
    park = snapshots["AYL_KARST_CAMUY_PARK"]
    assert park["current_status"] == "closed"
    assert park["status_quality"] == "verified"
    assert park["conflict_hold"] is False


def test_v11_conflicting_current_evidence_suppresses_open_projection() -> None:
    registry = load_default_registry()
    events = deepcopy(registry["events"])
    conflicting = {
        "event_id": "AYL_KEVT_CAMUY_V11_CONFLICT",
        "asset_id": "AYL_KARST_CAMUY_PARK",
        "event_type": "status_observation",
        "observed_at": "2026-08-07T21:00:00Z",
        "effective_from": "2026-08-07T21:00:00Z",
        "effective_to": None,
        "from_status": "unknown",
        "to_status": "open",
        "reason": "Synthetic v1.1 contradiction fixture.",
        "source_ref": "SRC_KARST_CTPR_REOPEN_20210317",
        "evidence_tier": "T2",
        "confidence": 60,
        "review_status": "accepted",
        "supersedes_event_id": None,
        "recorded_at": "2026-08-07T21:00:01Z",
        "previous_hash": events[-1]["record_hash"],
        "record_hash": "",
    }
    conflicting["record_hash"] = compute_record_hash(conflicting)
    events.append(conflicting)

    park = next(
        item
        for item in materialize_v11_status(registry["assets"], events, as_of=AS_OF)
        if item["asset_id"] == "AYL_KARST_CAMUY_PARK"
    )
    assert park["current_status"] == "unknown"
    assert park["status_quality"] == "conflicting"
    assert park["conflict_hold"] is True


def test_v11_stale_status_becomes_unknown_not_open() -> None:
    registry = load_default_registry()
    far_future = AS_OF + timedelta(days=31)
    park = next(
        item
        for item in materialize_v11_status(
            registry["assets"], registry["events"], as_of=far_future, stale_after_days=30
        )
        if item["asset_id"] == "AYL_KARST_CAMUY_PARK"
    )
    assert park["current_status"] == "unknown"
    assert park["status_quality"] == "stale"


def test_public_projection_redacts_sensitive_server_side_fields() -> None:
    registry = load_default_registry()
    asset = deepcopy(registry["assets"][0])
    asset["lat"] = 18.36
    asset["lon"] = -66.82
    asset["legal"]["parcel_refs"] = ["SENSITIVE-PARCEL"]
    asset["culture"]["heritage_registry_refs"] = ["SENSITIVE-HERITAGE"]
    asset["emergency"]["evacuation_route_ref"] = "CONTROLLED-ROUTE"
    asset["monitoring"]["sensor_ids"] = ["SEN_CAMUY_STAGE_01"]

    public = public_asset_projection(asset)
    assert public["lat"] is None and public["lon"] is None
    assert public["legal"]["parcel_refs"] == []
    assert public["culture"]["heritage_registry_refs"] == []
    assert public["emergency"]["evacuation_route_ref"] is None
    assert public["monitoring"]["sensor_ids"] == []
    assert validate_public_projection(public) == []


def test_p3_projection_hides_name_and_aliases() -> None:
    registry = load_default_registry()
    asset = deepcopy(registry["assets"][0])
    asset["privacy_class"] = "P3_RESTRICTED"
    public = public_asset_projection(asset)
    assert public["canonical_name"] == "Restricted cave/karst resource"
    assert public["aliases"] == []
    assert validate_public_projection(public) == []


def test_replay_has_zero_missed_severity_five_fixture_conditions() -> None:
    fixtures = [
        {"surveyed_evacuation_stage_exceeded": True},
        {"o2_pct": 19.4},
        {"co2_ppm": 30_000},
    ]
    for fixture in fixtures:
        alerts = evaluate_replay_sample(fixture)
        assert any(item["severity"] == 5 for item in alerts)
        assert all(item["ruleset_version"] == RULESET_VERSION for item in alerts)


def test_sensor_loss_never_emits_safe_or_open_action() -> None:
    alerts = evaluate_replay_sample({"sensor_heartbeats_missed": 2})
    assert alerts == [
        {
            "alert_type": "sensor_loss",
            "severity": 2,
            "action": "mark_telemetry_degraded",
            "ruleset_version": RULESET_VERSION,
        }
    ]
    assert all("open" not in item["action"] and "safe" not in item["action"] for item in alerts)


def test_jsonld_context_is_parseable_and_maps_provenance_and_sosa() -> None:
    context = json.loads(
        (SCHEMAS_DIR / "cave_karst_context.jsonld").read_text(encoding="utf-8")
    )["@context"]
    assert context["source"]["@id"] == "prov:wasDerivedFrom"
    assert context["madeBySensor"]["@id"] == "sosa:madeBySensor"
    assert context["featureOfInterest"]["@id"] == "sosa:hasFeatureOfInterest"


def test_pilot_contains_zero_inferred_entrance_geometry() -> None:
    registry = load_default_registry()
    cave_assets = [
        item
        for item in registry["assets"]
        if item["asset_kind"] in {"cave", "cave_system"}
    ]
    assert cave_assets
    assert all(item["geometry_type"] != "point" for item in cave_assets)
    assert all(item["lat"] is None and item["lon"] is None for item in cave_assets)


def test_cancelled_procurement_never_becomes_access_transition() -> None:
    registry = load_default_registry()
    procurement = next(
        item
        for item in registry["observations"]
        if item["metric"] == "repair_procurement_status"
    )
    assert procurement["value"] == "cancelled"
    assert all(
        item["source_ref"] != "SRC_KARST_ASG_REPAIR_20260617"
        for item in registry["events"]
    )
    park = next(
        item
        for item in materialize_v11_status(
            registry["assets"], registry["events"], as_of=AS_OF
        )
        if item["asset_id"] == "AYL_KARST_CAMUY_PARK"
    )
    assert park["current_status"] == "closed"
    assert park["status_event_id"] == "AYL_KEVT_CAMUY_CLOSED_OBS_20260803"
