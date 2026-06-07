"""Tests for `aguayluz.analysis.reconciliation.reconcile`."""

from __future__ import annotations

from aguayluz.analysis import Finding, reconcile
from aguayluz.models import validate_against_schema


def _asset(asset_id: str, municipality: str, status: str = "active") -> dict:
    return {
        "asset_id": asset_id,
        "asset_name": asset_id,
        "asset_type": "water",
        "asset_subtype": "intake",
        "municipality": municipality,
        "status": status,
        "lat": 18.388,
        "lon": -66.232,
        "geometry_type": "point",
        "source_ref": "https://example.gov",
        "evidence_tier": "T1",
        "confidence": 70,
        "review_status": "accepted",
    }


def _event(event_id: str, affected_area: str, step: str) -> dict:
    return {
        "event_id": event_id,
        "event_type": "project_update",
        "affected_area": affected_area,
        "source_ref": "https://www.fema.gov/example",
        "evidence_tier": "T2",
        "confidence": 45,
        "review_status": "needs_review",
        "linked_asset_ids": [],
        "notes": f"step={step}",
    }


# ---------- status_mismatch ----------


def test_damaged_asset_with_closed_fema_project_is_status_mismatch():
    findings, summary = reconcile(
        assets=[_asset("AYL_AST_X", "Bayamon", status="damaged")],
        events=[_event("AYL_EVT_20170920_fema_4339_pw1", "Bayamon, PR — Utilities", "Project Closed Out")],
    )
    mismatches = [f for f in findings if f.kind == "status_mismatch"]
    assert len(mismatches) == 1
    f = mismatches[0]
    assert f.severity == "critical"
    assert f.asset_id == "AYL_AST_X"
    assert f.event_id == "AYL_EVT_20170920_fema_4339_pw1"
    assert f.fema_step == "Project Closed Out"
    assert f.asset_status == "damaged"
    assert summary["status_mismatches"] == 1


def test_inactive_asset_with_closed_project_is_also_mismatch():
    findings, _ = reconcile(
        assets=[_asset("AYL_AST_X", "Bayamon", status="inactive")],
        events=[_event("AYL_EVT_20170920_fema_4339_pw1", "Bayamon, PR — Utilities", "Project Closed Out")],
    )
    assert any(f.kind == "status_mismatch" for f in findings)


# ---------- stale_asset ----------


def test_active_asset_with_inflight_fema_project_is_stale():
    findings, summary = reconcile(
        assets=[_asset("AYL_AST_X", "Bayamon", status="active")],
        events=[_event("AYL_EVT_20170920_fema_4339_pw1", "Bayamon, PR — Utilities", "Project Drawdown")],
    )
    stale = [f for f in findings if f.kind == "stale_asset"]
    assert len(stale) == 1
    assert stale[0].severity == "warn"
    assert summary["stale_assets"] == 1


def test_active_asset_with_obligated_project_is_stale():
    findings, _ = reconcile(
        assets=[_asset("AYL_AST_X", "Bayamon", status="active")],
        events=[_event("AYL_EVT_20170920_fema_4339_pw1", "Bayamon, PR — Utilities", "Project Obligated")],
    )
    assert any(f.kind == "stale_asset" for f in findings)


# ---------- missing_coverage ----------


def test_event_with_no_asset_in_muni_is_missing_coverage():
    findings, summary = reconcile(
        assets=[_asset("AYL_AST_X", "Bayamon")],
        events=[_event("AYL_EVT_20170920_fema_4339_pw1", "Yauco, PR — Water Control", "Project Closed Out")],
    )
    mc = [f for f in findings if f.kind == "missing_coverage"]
    assert len(mc) == 1
    assert mc[0].municipality == "Yauco"
    assert mc[0].asset_id is None
    assert mc[0].event_id == "AYL_EVT_20170920_fema_4339_pw1"
    assert summary["missing_coverage"] == 1


# ---------- consistent ----------


def test_asset_in_muni_with_no_fema_is_consistent():
    findings, summary = reconcile(
        assets=[_asset("AYL_AST_X", "Aguada")],
        events=[],
    )
    assert all(f.kind == "consistent" for f in findings)
    assert summary["consistent_count"] == 1


def test_active_asset_with_closed_fema_is_consistent():
    findings, summary = reconcile(
        assets=[_asset("AYL_AST_X", "Bayamon", status="active")],
        events=[_event("AYL_EVT_20170920_fema_4339_pw1", "Bayamon, PR — Utilities", "Project Closed Out")],
    )
    assert summary["consistent_count"] == 1
    assert summary["status_mismatches"] == 0


# ---------- pipeline / integration ----------


def test_empty_inputs_produce_no_findings():
    findings, summary = reconcile(assets=[], events=[])
    assert findings == []
    assert summary == {
        "consistent_count": 0,
        "status_mismatches": 0,
        "missing_coverage": 0,
        "stale_assets": 0,
    }


def test_full_demo_inputs_match_expected_shape():
    """Mirror the M5+M6 demo state: 3 assets (Bayamon×2, Catano×1) + 4 events
    (Yauco, Toa Alta, Catano, Ponce)."""
    assets = [
        _asset("AYL_AST_FRS_1", "Bayamon"),
        _asset("AYL_AST_FRS_2", "Bayamon"),
        _asset("AYL_AST_FRS_3", "Catano"),
    ]
    events = [
        _event("AYL_EVT_20010516_fema_1372_pw1", "Yauco, PR — Water Control", "Project Closed Out"),
        _event("AYL_EVT_20170920_fema_4339_pw2", "Toa Alta, PR — Utilities", "Project Obligated"),
        _event("AYL_EVT_20170920_fema_4339_pw3", "Catano, PR — Utilities", "Project Drawdown"),
        _event("AYL_EVT_20200227_fema_4473_pw4", "Ponce, PR — Utilities", "Project Closed Out"),
    ]
    findings, summary = reconcile(assets=assets, events=events)
    # 3 events have no matching assets → 3 missing_coverage.
    # 1 Catano event with an active asset + Drawdown → stale_asset.
    # 2 Bayamon assets have no events → 2 consistent.
    assert summary["missing_coverage"] == 3
    assert summary["stale_assets"] == 1
    assert summary["status_mismatches"] == 0
    assert summary["consistent_count"] >= 2


def test_finding_dict_validates_against_schema():
    findings, summary = reconcile(
        assets=[_asset("AYL_AST_X", "Bayamon", status="damaged")],
        events=[_event("AYL_EVT_20170920_fema_4339_pw1", "Bayamon, PR — Utilities", "Project Closed Out")],
    )
    report = {
        "module_id": "aguayluz-pr",
        "run_id": "20260606T120000Z_test",
        "vector": "AGUAYLUZ_RECONCILE_PROJECT_STATUS",
        "generated_at": "2026-06-06T12:00:00Z",
        "findings": [f.model_dump() for f in findings],
        "summary": summary,
    }
    validate_against_schema("reconciliation_report", report)


def test_finding_id_is_stable_per_input():
    """Same inputs → same finding_id (SHA-1 over a deterministic seed)."""
    assets = [_asset("AYL_AST_X", "Bayamon", status="damaged")]
    events = [_event("AYL_EVT_20170920_fema_4339_pw1", "Bayamon, PR — Utilities", "Project Closed Out")]
    a, _ = reconcile(assets=assets, events=events)
    b, _ = reconcile(assets=assets, events=events)
    assert [f.finding_id for f in a] == [f.finding_id for f in b]


def test_finding_dataclass_dump_shape():
    f = Finding(
        finding_id="AYL_FIND_abc",
        kind="consistent",
        severity="info",
        municipality="Bayamon",
        details="test",
        confidence=50,
    )
    d = f.model_dump()
    assert d["asset_id"] is None
    assert d["event_id"] is None
    assert "kind" in d and d["kind"] == "consistent"
