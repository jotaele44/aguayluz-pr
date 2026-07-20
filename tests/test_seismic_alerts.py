"""Tests for the SEISMIC_GEO alert promoter (aguayluz.alert_promotion.seismic)."""

from __future__ import annotations

from aguayluz.alert_promotion import is_critical
from aguayluz.alert_promotion.seismic import seismic_alert, seismic_alerts
from aguayluz.water_alerts import load_geo

GEO = load_geo([
    {"name": "Rincón", "lat": 18.34, "lon": -67.25},
    {"name": "Ponce", "lat": 18.011, "lon": -66.614},
])


def _quake(**over):
    ev = {
        "event_id": "AYL_EVT_20260718_USGS-EQ-pr71524858",
        "event_type": "service_interruption",
        "affected_area": "27 km NW of Rincón, Puerto Rico",
        "municipality": None,
        "status_text": "earthquake M2.91 depth=18.53 km place='27 km NW of Rincón, Puerto Rico' source='pr'",
        "start_time": "2026-07-18T15:47:56Z",
        "source_ref": "USGS-EQ:pr71524858",
        "evidence_tier": "T1",
        "confidence": 85,
        "review_status": "accepted",
        "linked_asset_ids": [],
    }
    ev.update(over)
    return ev


def test_quake_promotes_to_seismic_geo_alert():
    a = seismic_alert(_quake(), GEO)
    assert a is not None
    assert a.module_id == "SEISMIC_GEO"
    assert a.event_type == "hazard"
    assert a.evidence_tier == "T1"
    assert "_seismic_" in a.alert_id
    assert a.severity == 1  # M2.91 < 3.0 -> lowest band


def test_magnitude_severity_bands():
    assert seismic_alert(_quake(status_text="earthquake M2.9 depth=5"), GEO).severity == 1
    assert seismic_alert(_quake(status_text="earthquake M3.4 depth=5"), GEO).severity == 2
    assert seismic_alert(_quake(status_text="earthquake M4.5 depth=5"), GEO).severity == 3
    assert seismic_alert(_quake(status_text="earthquake M5.2 depth=5"), GEO).severity == 4
    assert seismic_alert(_quake(status_text="earthquake M6.7 depth=5"), GEO).severity == 5


def test_major_quake_is_critical():
    a = seismic_alert(_quake(status_text="earthquake M6.1 depth=10 place='Ponce, Puerto Rico'"), GEO)
    assert a.severity == 5
    assert is_critical(a.severity, a.status) is True


def test_minor_quake_not_critical():
    a = seismic_alert(_quake(), GEO)  # M2.91
    assert is_critical(a.severity, a.status) is False


def test_place_resolves_municipality_centroid():
    a = seismic_alert(_quake(), GEO)
    assert a.municipalities == ["Rincón"]
    assert a.latitude == 18.34 and a.longitude == -67.25
    assert a.coord_confidence == "approximate"


def test_non_seismic_event_is_ignored():
    non = _quake(source_ref="EPA SDWIS VIOLATION", status_text="viol=21 health_based=Y")
    assert seismic_alert(non, GEO) is None


def test_seismic_alerts_filters_stream():
    events = [_quake(), {"source_ref": "NWS", "status_text": "event='Flood Warning'"}]
    out = seismic_alerts(events, GEO)
    assert len(out) == 1 and out[0].module_id == "SEISMIC_GEO"
