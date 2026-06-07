"""Tests for `aguayluz.analysis.municipalities.aggregate_by_municipality`."""

from __future__ import annotations

from aguayluz.analysis import aggregate_by_municipality
from aguayluz.models import validate_against_schema


def _asset(asset_id, municipality="Bayamon", asset_type="water", **kw):  # type: ignore[no-untyped-def]
    base = {
        "asset_id": asset_id,
        "asset_name": asset_id,
        "asset_type": asset_type,
        "asset_subtype": "intake",
        "municipality": municipality,
        "status": "active",
        "lat": 18.4,
        "lon": -66.2,
        "geometry_type": "point",
        "source_ref": "https://example.gov",
        "evidence_tier": "T1",
        "confidence": 70,
        "review_status": "accepted",
    }
    base.update(kw)
    return base


def _event(event_id, affected_area="Bayamon, PR — Utilities", step="Project Obligated", **kw):  # type: ignore[no-untyped-def]
    base = {
        "event_id": event_id,
        "event_type": "project_update",
        "affected_area": affected_area,
        "review_status": "needs_review",
        "start_time": "2017-09-20T00:00:00Z",
        "notes": f"step={step}",
        "evidence_tier": "T2",
        "confidence": 45,
        "source_ref": "https://example.gov",
    }
    base.update(kw)
    return base


# ---------- bucketization ----------


def test_assets_split_across_municipalities():
    summaries, unattributed = aggregate_by_municipality(
        assets=[
            _asset("A1", municipality="Bayamon"),
            _asset("A2", municipality="Catano"),
            _asset("A3", municipality="Bayamon", asset_type="power"),
        ],
        events=[],
    )
    by_muni = {s["municipality"]: s for s in summaries}
    assert by_muni["Bayamon"]["asset_counts"]["total"] == 2
    assert by_muni["Bayamon"]["asset_counts"]["by_type"] == {"water": 1, "power": 1}
    assert by_muni["Catano"]["asset_counts"]["total"] == 1
    assert unattributed["asset_total"] == 0


def test_municipality_normalization_is_casefold():
    summaries, _ = aggregate_by_municipality(
        assets=[
            _asset("A1", municipality="Bayamon"),
            _asset("A2", municipality="BAYAMON"),
            _asset("A3", municipality="bayamón"),
        ],
        events=[],
    )
    # Three case-variants → one bucket of three assets.
    assert len(summaries) == 1
    assert summaries[0]["asset_counts"]["total"] == 3


def test_events_bucketize_by_affected_area_head():
    summaries, _ = aggregate_by_municipality(
        assets=[],
        events=[
            _event("E1", affected_area="Yauco, PR — Water Control"),
            _event("E2", affected_area="Yauco, PR — Utilities"),
        ],
    )
    assert len(summaries) == 1
    assert summaries[0]["municipality"] == "Yauco"
    assert summaries[0]["service_events_total"] == 2


def test_unattributed_records_go_to_bucket():
    summaries, unattributed = aggregate_by_municipality(
        assets=[
            _asset("A1", municipality="Bayamon"),
            _asset("A2", municipality=""),
        ],
        events=[
            _event("E1", affected_area=""),
        ],
    )
    assert summaries[0]["asset_counts"]["total"] == 1
    assert unattributed["asset_total"] == 1
    assert unattributed["event_total"] == 1


# ---------- field computations ----------


def test_active_event_counts_non_closed_steps():
    summaries, _ = aggregate_by_municipality(
        assets=[_asset("A1")],
        events=[
            _event("E1", step="Project Obligated"),
            _event("E2", step="Project Closed Out"),
            _event("E3", step="Project Drawdown"),
        ],
    )
    bayamon = next(s for s in summaries if s["municipality"] == "Bayamon")
    assert bayamon["service_events_total"] == 3
    assert bayamon["active_events"] == 2  # Closed Out excluded


def test_partial_coverage_counted():
    summaries, _ = aggregate_by_municipality(
        assets=[
            _asset("A1", attribute_coverage="partial"),
            _asset("A2", attribute_coverage="full"),
            _asset("A3", attribute_coverage="partial"),
        ],
        events=[],
    )
    assert summaries[0]["partial_coverage_count"] == 2


def test_watershed_area_sums_per_asset():
    summaries, _ = aggregate_by_municipality(
        assets=[_asset("A1"), _asset("A2")],
        events=[],
        watersheds=[
            {"asset_id": "A1", "area_sqkm": 100.0},
            {"asset_id": "A2", "area_sqkm": 50.0},
        ],
    )
    assert summaries[0]["watershed_area_sqkm_total"] == 150.0


def test_contradictions_split_by_severity():
    summaries, _ = aggregate_by_municipality(
        assets=[_asset("A1")],
        events=[],
        findings=[
            {"municipality": "Bayamon", "severity": "warn", "kind": "stale_asset", "details": "x"},
            {"municipality": "Bayamon", "severity": "critical", "kind": "status_mismatch", "details": "y"},
            {"municipality": "Bayamon", "severity": "info", "kind": "consistent", "details": "z"},
        ],
    )
    summary = summaries[0]
    assert summary["contradictions_summary"]["warn"] == 1
    assert summary["contradictions_summary"]["critical"] == 1


def test_top_findings_orders_critical_before_warn():
    summaries, _ = aggregate_by_municipality(
        assets=[_asset("A1")],
        events=[],
        findings=[
            {"municipality": "Bayamon", "severity": "warn", "kind": "stale_asset", "details": "warn1"},
            {"municipality": "Bayamon", "severity": "critical", "kind": "status_mismatch", "details": "crit1"},
            {"municipality": "Bayamon", "severity": "info", "kind": "consistent", "details": "info1"},
            {"municipality": "Bayamon", "severity": "warn", "kind": "stale_asset", "details": "warn2"},
        ],
    )
    top = summaries[0]["top_findings"]
    assert len(top) == 3  # cap at 3
    assert top[0]["severity"] == "critical"
    assert top[1]["severity"] == "warn"


def test_top_findings_truncates_long_details():
    long_detail = "x" * 300
    summaries, _ = aggregate_by_municipality(
        assets=[_asset("A1")],
        events=[],
        findings=[
            {"municipality": "Bayamon", "severity": "warn", "kind": "stale_asset", "details": long_detail},
        ],
    )
    details = summaries[0]["top_findings"][0]["details"]
    assert len(details) == 200
    assert details.endswith("…")


# ---------- ordering ----------


def test_summaries_sorted_by_asset_count_descending():
    summaries, _ = aggregate_by_municipality(
        assets=[
            _asset("A1", municipality="Catano"),
            _asset("A2", municipality="Bayamon"),
            _asset("A3", municipality="Bayamon"),
            _asset("A4", municipality="Bayamon"),
        ],
        events=[_event("E1", affected_area="Aguada, PR — Utilities")],
    )
    # Bayamon (3 assets) > Catano (1 asset) > Aguada (0 assets, only event)
    assert [s["municipality"] for s in summaries] == ["Bayamon", "Catano", "Aguada"]


# ---------- schema round-trip ----------


def test_payload_validates_against_schema():
    summaries, unattributed = aggregate_by_municipality(
        assets=[_asset("A1", attribute_coverage="partial")],
        events=[_event("E1")],
        findings=[
            {"municipality": "Bayamon", "severity": "warn",
             "kind": "stale_asset", "details": "test"},
        ],
        watersheds=[{"asset_id": "A1", "area_sqkm": 100.0}],
    )
    payload = {
        "module_id": "aguayluz-pr",
        "generated_at": "2026-06-06T12:00:00Z",
        "municipalities": summaries,
        "unattributed": unattributed,
    }
    validate_against_schema("municipality_summary", payload)


def test_empty_inputs_produce_valid_empty_payload():
    summaries, unattributed = aggregate_by_municipality(assets=[], events=[])
    payload = {
        "module_id": "aguayluz-pr",
        "generated_at": "2026-06-06T12:00:00Z",
        "municipalities": summaries,
        "unattributed": unattributed,
    }
    validate_against_schema("municipality_summary", payload)
    assert summaries == []
    assert unattributed == {"asset_total": 0, "event_total": 0}
