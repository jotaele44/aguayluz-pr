"""Tests for the data-driven water alert generator (aguayluz.water_alerts)."""

from __future__ import annotations

from aguayluz.water_alerts import (
    build_water_alerts,
    contamination_alert,
    load_geo,
    reservoir_alerts,
)

GEO = load_geo([
    {"name": "Bayamón", "lat": 18.398, "lon": -66.155},
    {"name": "Maunabo", "lat": 18.007, "lon": -65.899},
])


def _boil_water(**over):
    ev = {
        "event_id": "AYL_EVT_20150701_PR0002591_7613967",
        "event_type": "boil_water",
        "affected_area": "BAYAMON,SAN JUAN,TOA ALTA",
        "municipality": "Bayamón",
        "status_text": "viol=21 contaminant=3100 health_based=Y pn_tier=1 compliance=A",
        "start_time": "2015-07-01T00:00:00Z",
        "end_time": "2015-07-31T00:00:00Z",
        "source_ref": "EPA SDWIS VIOLATION pwsid=PR0002591 violation_id=7613967",
        "evidence_tier": "T1",
        "confidence": 80,
        "review_status": "accepted",
        "linked_asset_ids": [],
    }
    ev.update(over)
    return ev


def test_boil_water_acute_maps_to_contamination_alert():
    a = contamination_alert(_boil_water(), GEO)
    assert a is not None
    assert a.module_id == "CONTAMINATION"
    assert a.event_type == "quality"
    assert a.severity == 4  # acute (pn_tier=1)
    assert a.evidence_tier == "T1"
    assert a.status == "active"  # compliance != R
    assert a.municipalities == ["Bayamón"]
    # geolocated via municipio centroid
    assert a.latitude == 18.398 and a.longitude == -66.155
    assert a.coord_confidence == "approximate"
    assert a.alert_id.startswith("AYL_ALR_20150701_sdwis_")


def test_boil_water_non_acute_lower_severity():
    a = contamination_alert(_boil_water(status_text="health_based=Y pn_tier=2 compliance=R"), GEO)
    assert a.severity == 3
    assert a.status == "closed"  # compliance == R -> returned to compliance


def test_health_based_quality_violation_becomes_alert():
    ev = _boil_water(event_type="water_quality_violation",
                     status_text="health_based=Y pn_tier=2 compliance=A", municipality="Maunabo")
    a = contamination_alert(ev, GEO)
    assert a is not None
    assert a.module_id == "CONTAMINATION"
    assert a.severity == 2


def test_non_health_violation_is_not_alerted():
    ev = _boil_water(event_type="water_quality_violation",
                     status_text="health_based=N pn_tier=3 compliance=A")
    assert contamination_alert(ev, GEO) is None


def test_non_contamination_event_ignored():
    assert contamination_alert(_boil_water(event_type="outage"), GEO) is None


def test_unknown_municipality_yields_unscoped_no_coords():
    ev = _boil_water(municipality="unknown", affected_area="")
    a = contamination_alert(ev, GEO)
    assert a.coord_confidence == "unknown"
    assert a.latitude is None


# ---------------- reservoir proxy ----------------

def _readings(asset_id, values, metric="reservoir_storage_pct"):
    return [
        {"asset_id": asset_id, "asset_name": "Lago X", "metric": metric,
         "value": v, "date": f"2026-01-{i + 1:02d}", "municipality": "Maunabo",
         "source_ref": f"USGS {asset_id}"}
        for i, v in enumerate(values)
    ]


def test_reservoir_low_flags_lower_tail():
    # 20 readings; latest (last) is the minimum -> below the 10th percentile.
    vals = list(range(100, 60, -2))  # descending, so the last is lowest & newest
    alerts = reservoir_alerts(_readings("USGS_1", vals), GEO, percentile=10.0, min_history=12)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.module_id == "HYDRO_OPS"
    assert a.evidence_tier == "T2"          # proxy, not official
    assert a.review_status == "needs_review"
    assert a.gap_status == "major"
    assert "Statistical proxy" in (a.validation_notes or "")


def test_reservoir_normal_level_no_alert():
    # latest reading is the HIGHEST -> not in the lower tail.
    vals = list(range(60, 100, 2))  # ascending, last is highest & newest
    alerts = reservoir_alerts(_readings("USGS_2", vals), GEO, percentile=10.0, min_history=12)
    assert alerts == []


def test_reservoir_short_history_skipped():
    alerts = reservoir_alerts(_readings("USGS_3", [10, 9, 8]), GEO, min_history=12)
    assert alerts == []


def test_build_water_alerts_combines_sources():
    events = [_boil_water(), _boil_water(event_type="water_quality_violation",
                                         status_text="health_based=N")]
    readings = _readings("USGS_1", list(range(100, 60, -2)))
    alerts = build_water_alerts(events, readings, GEO)
    mods = sorted({a.module_id for a in alerts})
    assert mods == ["CONTAMINATION", "HYDRO_OPS"]
