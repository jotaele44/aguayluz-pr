"""Tests for the WEATHER_HAZARD alert promoter (aguayluz.alert_promotion.weather)."""

from __future__ import annotations

from aguayluz.alert_promotion import is_critical
from aguayluz.alert_promotion.weather import weather_alert, weather_alerts
from aguayluz.water_alerts import load_geo

GEO = load_geo([{"name": "Ponce", "lat": 18.011, "lon": -66.614}])


def _nws(event_name, severity="Moderate", **over):
    ev = {
        "event_id": "AYL_EVT_20260706_NWS-001-1",
        "event_type": "service_interruption",
        "affected_area": "San Juan and Vicinity; Northeast; Southeast",
        "municipality": None,
        "status_text": f"event='{event_name}' severity={severity} sender='NWS San Juan PR'",
        "start_time": "2026-07-06T02:31:00-04:00",
        "end_time": "2026-07-06T17:00:00-04:00",
        "source_ref": "urn:oid:2.49.0.1.840.0.abc.001.1",
        "evidence_tier": "T1",
        "confidence": 85,
        "review_status": "accepted",
        "linked_asset_ids": [],
    }
    ev.update(over)
    return ev


def test_nws_event_promotes_to_weather_hazard_alert():
    a = weather_alert(_nws("Heat Advisory"), GEO)
    assert a is not None
    assert a.module_id == "WEATHER_HAZARD"
    assert a.event_type == "hazard"
    assert a.evidence_tier == "T1"
    assert "_weather_" in a.alert_id
    assert a.severity == 2  # heat advisory -> moderate


def test_hazard_severity_bands():
    assert weather_alert(_nws("Hurricane Warning", "Extreme"), GEO).severity == 5
    assert weather_alert(_nws("Tropical Storm Warning", "Severe"), GEO).severity == 4
    assert weather_alert(_nws("Storm Surge Warning", "Severe"), GEO).severity == 4
    assert weather_alert(_nws("Flash Flood Warning", "Severe"), GEO).severity == 4
    assert weather_alert(_nws("Flood Warning", "Moderate"), GEO).severity == 3
    assert weather_alert(_nws("Heat Advisory", "Minor"), GEO).severity == 1  # minor drops 2->1


def test_hurricane_warning_is_critical():
    a = weather_alert(_nws("Hurricane Warning", "Extreme"), GEO)
    assert a.severity == 5
    assert is_critical(a.severity, a.status) is True


def test_heat_advisory_not_critical():
    a = weather_alert(_nws("Heat Advisory"), GEO)
    assert is_critical(a.severity, a.status) is False


def test_area_municipality_centroid_when_named():
    a = weather_alert(_nws("Flood Warning", affected_area="Ponce; Southeast"), GEO)
    assert a.municipalities == ["Ponce"]
    assert a.latitude == 18.011 and a.longitude == -66.614


def test_unnamed_area_is_unscoped():
    a = weather_alert(_nws("Heat Advisory"), GEO)  # "San Juan and Vicinity" not a bare municipio
    assert a.municipalities == ["(unscoped)"]
    assert a.coord_confidence == "unknown"


def test_non_nws_event_ignored():
    quake = {"source_ref": "USGS-EQ:x", "status_text": "earthquake M4.0 depth=5"}
    assert weather_alert(quake, GEO) is None


def test_weather_alerts_filters_stream():
    events = [_nws("Hurricane Warning"), {"source_ref": "USGS-EQ:x", "status_text": "earthquake M4.0"}]
    out = weather_alerts(events, GEO)
    assert len(out) == 1 and out[0].module_id == "WEATHER_HAZARD"
