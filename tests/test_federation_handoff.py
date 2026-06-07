"""Tests for `aguayluz.federation.build_handoff_payload`."""

from __future__ import annotations

from aguayluz.federation import (
    HANDOFF_VECTOR,
    _disaster_number,
    _time_window,
    build_handoff_payload,
)
from aguayluz.models import validate_against_schema

RUN_ID = "20260606T120000Z_test"


def _asset(asset_id, **kw):  # type: ignore[no-untyped-def]
    base = {
        "asset_id": asset_id,
        "municipality": "Bayamon",
        "comid": 21000100,
        "reachcode": "21010002000001",
        "vpuid": "21",
        "attribute_coverage": "partial",
    }
    base.update(kw)
    return base


def _event(event_id, **kw):  # type: ignore[no-untyped-def]
    base = {
        "event_id": event_id,
        "affected_area": "Bayamon, PR — Utilities",
        "review_status": "needs_review",
        "notes": "step=Project Obligated",
        "start_time": "2017-09-20T00:00:00Z",
    }
    base.update(kw)
    return base


# ---------- helpers ----------


def test_disaster_number_parses_event_id():
    assert _disaster_number("AYL_EVT_20170920_fema_4339_pw911234") == "4339"


def test_disaster_number_returns_none_without_fema():
    assert _disaster_number("AYL_EVT_20260101_otherprefix") is None


def test_time_window_picks_earliest_and_latest():
    events = [
        _event("E1", start_time="2017-09-20T00:00:00Z"),
        _event("E2", start_time="2020-02-27T00:00:00Z"),
    ]
    assert _time_window(events) == {"from": "2017-09-20", "to": "2020-02-27"}


def test_time_window_empty_returns_none():
    assert _time_window([]) is None


# ---------- moneysweep-pr ----------


def test_moneysweep_payload_extracts_fema_disaster_numbers():
    events = [_event("AYL_EVT_20170920_fema_4339_pw911234")]
    handoff = build_handoff_payload(
        "moneysweep-pr", run_id=RUN_ID, assets=[_asset("A1")], events=events,
    )
    keys = handoff["join_keys"]
    assert any(k["key_type"] == "fema_disaster_number" and k["value"] == "4339" for k in keys)
    assert handoff["payload"]["fema_events"][0]["fema_disaster_number"] == "4339"


def test_moneysweep_skips_non_fema_events():
    handoff = build_handoff_payload(
        "moneysweep-pr", run_id=RUN_ID,
        assets=[], events=[_event("AYL_EVT_20260101_other", )],
    )
    assert handoff["join_keys"] == []
    assert handoff["payload"]["fema_events"] == []


# ---------- spiderweb-pr ----------


def test_spiderweb_payload_emits_nhdplus_join_keys():
    handoff = build_handoff_payload(
        "spiderweb-pr", run_id=RUN_ID,
        assets=[_asset("A1")], events=[],
    )
    key_types = {k["key_type"] for k in handoff["join_keys"]}
    assert key_types == {"comid", "reachcode"}
    nhdplus_assets = handoff["payload"]["nhdplus_assets"]
    assert nhdplus_assets[0]["asset_id"] == "A1"
    assert nhdplus_assets[0]["vpuid"] == "21"


def test_spiderweb_includes_watersheds_when_provided():
    handoff = build_handoff_payload(
        "spiderweb-pr", run_id=RUN_ID,
        assets=[_asset("A1")], events=[],
        watersheds=[{
            "asset_id": "A1",
            "nhdplus_id": 21000100,
            "area_sqkm": 142.6,
            "bounds_bbox": [-66.3, 18.3, -66.2, 18.4],
        }],
    )
    assert handoff["payload"]["watersheds"][0]["asset_id"] == "A1"
    assert handoff["payload"]["watersheds"][0]["area_sqkm"] == 142.6


def test_spiderweb_filters_assets_missing_nhdplus_keys():
    no_comid = _asset("A_NULL")
    no_comid["comid"] = None
    no_comid["reachcode"] = None
    handoff = build_handoff_payload(
        "spiderweb-pr", run_id=RUN_ID,
        assets=[_asset("A1"), no_comid], events=[],
    )
    assert len(handoff["payload"]["nhdplus_assets"]) == 1


# ---------- thehub-pr ----------


def test_thehub_payload_includes_critical_and_warn_findings():
    handoff = build_handoff_payload(
        "thehub-pr", run_id=RUN_ID,
        assets=[_asset("A1")], events=[],
        findings=[
            {"finding_id": "F1", "kind": "stale_asset", "severity": "warn",
             "municipality": "Bayamon", "details": "x"},
            {"finding_id": "F2", "kind": "consistent", "severity": "info",
             "municipality": "Bayamon", "details": "y"},
            {"finding_id": "F3", "kind": "status_mismatch", "severity": "critical",
             "municipality": "Catano", "details": "z"},
        ],
        bridge_summary={"assets_total": 1, "events_total": 0},
    )
    contradictions = handoff["payload"]["contradictions"]
    severities = {c["severity"] for c in contradictions}
    assert severities == {"warn", "critical"}  # info dropped
    assert handoff["payload"]["bridge_summary"]["assets_total"] == 1


# ---------- default target ----------


def test_default_payload_carries_municipalities():
    handoff = build_handoff_payload(
        "skywatcher-pr", run_id=RUN_ID,
        assets=[_asset("A1", municipality="Bayamon"),
                _asset("A2", municipality="Catano")],
        events=[_event("E1")],
    )
    assert handoff["payload"]["asset_count"] == 2
    assert sorted(handoff["payload"]["municipalities"]) == ["Bayamon", "Catano"]
    assert all(k["key_type"] == "municipality" for k in handoff["join_keys"])


# ---------- envelope shape + schema ----------


def test_envelope_shape_is_complete():
    handoff = build_handoff_payload(
        "moneysweep-pr", run_id=RUN_ID, assets=[], events=[],
    )
    for key in (
        "module_id", "target_module_id", "run_id", "vector", "generated_at",
        "time_window", "confidence_floor", "join_keys", "payload",
    ):
        assert key in handoff
    assert handoff["module_id"] == "aguayluz-pr"
    assert handoff["vector"] == HANDOFF_VECTOR


def test_handoff_validates_against_schema():
    handoff = build_handoff_payload(
        "spiderweb-pr", run_id=RUN_ID,
        assets=[_asset("A1")], events=[_event("AYL_EVT_20170920_fema_4339_pw1")],
        watersheds=[{
            "asset_id": "A1",
            "nhdplus_id": 21000100,
            "area_sqkm": 100.0,
            "bounds_bbox": [-66.3, 18.3, -66.2, 18.4],
        }],
    )
    validate_against_schema("federation_handoff", handoff)


def test_handoff_for_each_target_validates():
    """Round-trip every distinct receiver through the schema."""
    targets = ["moneysweep-pr", "spiderweb-pr", "thehub-pr", "skywatcher-pr", "ovnis-pr"]
    for target in targets:
        handoff = build_handoff_payload(
            target, run_id=RUN_ID,
            assets=[_asset("A1")],
            events=[_event("AYL_EVT_20170920_fema_4339_pw1")],
        )
        validate_against_schema("federation_handoff", handoff)
