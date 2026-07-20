"""Tests for the INDUSTRIAL alert promoter (aguayluz.alert_promotion.osha)."""

from __future__ import annotations

from aguayluz.alert_promotion import is_critical
from aguayluz.alert_promotion.osha import osha_alert, osha_alerts
from aguayluz.water_alerts import load_geo

GEO = load_geo([
    {"name": "Bayamón", "lat": 18.40, "lon": -66.15},
    {"name": "Ponce", "lat": 18.011, "lon": -66.614},
])


def _osha(**over):
    ev = {
        "event_id": "AYL_EVT_20260512_OSHA-317405066",
        "event_type": "unknown",
        "affected_area": "Bayamón",
        "municipality": "Bayamón",
        "status_text": "osha inspection activity_nr=317405066 estab='ACME MFG' "
                       "insp_type='Fatality/Catastrophe' naics=331110 city='Bayamón'",
        "start_time": "2026-05-12T00:00:00Z",
        "source_ref": "OSHA ENFORCEMENT activity_nr=317405066",
        "evidence_tier": "T1",
        "confidence": 85,
        "review_status": "needs_review",
        "linked_asset_ids": [],
    }
    ev.update(over)
    return ev


def test_inspection_promotes_to_industrial_alert():
    a = osha_alert(_osha(), GEO)
    assert a is not None
    assert a.module_id == "INDUSTRIAL"
    assert a.event_type == "hazard"
    assert a.evidence_tier == "T1"
    assert "_osha_" in a.alert_id
    assert a.severity == 5  # Fatality/Catastrophe -> life-safety band


def test_inspection_type_severity_bands():
    def sev(insp_type):
        st = f"osha inspection activity_nr=1 estab='X' insp_type='{insp_type}' naics=1 city='Ponce'"
        return osha_alert(_osha(status_text=st, municipality=None), GEO).severity
    assert sev("Fatality/Catastrophe") == 5
    assert sev("Accident") == 4
    assert sev("Complaint") == 3
    assert sev("Referral") == 3
    assert sev("Programmed Planned") == 2


def test_fatality_inspection_is_critical():
    a = osha_alert(_osha(), GEO)
    assert a.severity == 5
    assert is_critical(a.severity, a.status) is True


def test_closed_fatality_inspection_is_not_critical():
    # A closed historical fatality (end_time set) is severity 5 but must NOT be a
    # current push/SMS hazard — it becomes a `closed` alert that is_critical excludes.
    a = osha_alert(_osha(end_time="2019-11-20T00:00:00Z"), GEO)
    assert a.severity == 5
    assert a.status == "closed"
    assert a.end_at == "2019-11-20T00:00:00Z"
    assert is_critical(a.severity, a.status) is False


def test_open_inspection_status_active():
    a = osha_alert(_osha(), GEO)  # no end_time
    assert a.status == "active"
    assert a.end_at is None


def test_programmed_inspection_not_critical():
    st = "osha inspection activity_nr=2 estab='Y' insp_type='Programmed Planned' naics=1 city='Ponce'"
    a = osha_alert(_osha(status_text=st, municipality="Ponce"), GEO)
    assert a.severity == 2
    assert is_critical(a.severity, a.status) is False


def test_municipality_resolves_centroid():
    a = osha_alert(_osha(), GEO)
    assert a.municipalities == ["Bayamón"]
    assert a.latitude == 18.40 and a.longitude == -66.15
    assert a.coord_confidence == "approximate"


def test_non_osha_event_is_ignored():
    non = _osha(source_ref="USGS-EQ:pr123", status_text="earthquake M4.2")
    assert osha_alert(non, GEO) is None


def test_osha_alerts_filters_stream():
    events = [_osha(), {"source_ref": "EPA SDWIS VIOLATION", "status_text": "viol=21"}]
    out = osha_alerts(events, GEO)
    assert len(out) == 1 and out[0].module_id == "INDUSTRIAL"
