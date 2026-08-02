"""aguayluz.alert_promotion.nhc — NHC cyclone service-events -> WEATHER_HAZARD alerts.

Every emitted alert is validated against the real schemas/alert_event.schema.json.

Regression origin: the NHC ingest originally stopped at a raw service_event.
weather_alert() keys on the ``event='…'`` marker that ingest_nws_alerts.py writes and
returns None for anything else, so a hurricane entering the corridor produced a row
nothing acted on — defeating the reason the feed exists, since its whole value over the
NWS feed is lead time.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from aguayluz.alert_promotion import (  # noqa: E402
    CRITICAL_SEVERITY,
    GENERATED_MARKERS,
    build_all_alerts,
    is_critical,
)
from aguayluz.alert_promotion.nhc import (  # noqa: E402
    NHC_MARKER,
    nhc_alert,
    nhc_alerts,
    storm_severity,
)
from ingest_nhc_storms import build_events  # noqa: E402

ALERT_SCHEMA = json.loads((REPO / "schemas" / "alert_event.schema.json").read_text())
ALERT_ID_PATTERN = ALERT_SCHEMA["properties"]["alert_id"]["pattern"]


def _storm(**over) -> dict:
    base = {
        "id": "al052026", "name": "Bertha", "classification": "HU",
        "intensity": "85", "pressure": "968",
        "latitudeNumeric": 17.4, "longitudeNumeric": -64.2,
        "movementDir": 285, "movementSpeed": 13,
        "lastUpdate": "2026-08-02T03:00:00.000Z",
        "publicAdvisory": {"advNum": "014", "issuance": "2026-08-02T03:00:00.000Z",
                           "url": "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"},
    }
    base.update(over)
    return base


def _event(**over) -> dict:
    """A real service_event row, built by the ingest rather than hand-written — so the
    promoter is tested against the shape the producer actually emits."""
    events, _ = build_events({"activeStorms": [_storm(**over)]})
    assert events, "the ingest filtered this storm out; adjust the fixture"
    return events[0]


# ── the regression ────────────────────────────────────────────────────────────
def test_an_nhc_event_now_becomes_a_weather_hazard_alert():
    alert = nhc_alert(_event())
    assert alert is not None
    assert alert.module_id == "WEATHER_HAZARD"
    assert alert.event_type == "hazard"
    jsonschema.validate(alert.model_dump(), ALERT_SCHEMA)


def test_the_nws_promoter_still_does_not_claim_nhc_rows():
    """The two promoters must stay disjoint, or one storm yields two alerts."""
    from aguayluz.alert_promotion.weather import weather_alert

    assert weather_alert(_event(), {}) is None


def test_nhc_promoter_ignores_rows_from_every_other_source():
    for source_ref in ("urn:oid:2.49.0.1.840.0.abc.001.1", "SDWIS PR0002000",
                       "OSHA ENFORCEMENT 12345", "", "NHC"):
        assert nhc_alert({"source_ref": source_ref, "status_text": "x"}) is None


def test_build_all_alerts_wires_the_promoter_in():
    alerts = build_all_alerts([_event()], None, {}, [])
    assert [a for a in alerts if NHC_MARKER in a.alert_id]


def test_marker_is_registered_for_idempotent_merge():
    assert NHC_MARKER in GENERATED_MARKERS


# ── severity: classification AND distance ─────────────────────────────────────
def test_a_close_hurricane_clears_the_push_threshold():
    alert = nhc_alert(_event(latitudeNumeric=18.2, longitudeNumeric=-66.4))
    assert alert.severity >= CRITICAL_SEVERITY
    assert is_critical(alert.severity, alert.status)


def test_the_same_hurricane_far_away_does_not():
    """A Category 4 off Cabo Verde and one six hours out are the same classification
    string and nowhere near the same alert. Treating them alike trains operators to
    ignore both — which is why this promoter exists instead of an `event='…'` marker."""
    near = nhc_alert(_event(latitudeNumeric=18.2, longitudeNumeric=-66.4))
    far = nhc_alert(_event(latitudeNumeric=14.0, longitudeNumeric=-55.0))
    assert far.severity < CRITICAL_SEVERITY < near.severity + 1
    assert not is_critical(far.severity, far.status)


def test_a_nearby_depression_does_not_push():
    alert = nhc_alert(_event(classification="TD"))
    assert not is_critical(alert.severity, alert.status)


def test_a_nearby_tropical_storm_does_push():
    alert = nhc_alert(_event(classification="TS"))
    assert is_critical(alert.severity, alert.status)


@pytest.mark.parametrize("code,expected_order", [("MH", 4), ("HU", 4), ("TS", 3),
                                                 ("TD", 2), ("PTC", 2), ("DB", 1)])
def test_classification_severity_is_ordered(code, expected_order):
    assert storm_severity(code, distance_km=None) == expected_order


def test_severity_never_leaves_the_schema_range():
    for code in ("MH", "HU", "TS", "TD", "PTC", "DB", "", "NONSENSE"):
        for km in (0.0, 250.0, 750.0, 5000.0, None):
            sev = storm_severity(code, km)
            assert 0 <= sev <= 5


def test_distance_scaling_is_monotonic_for_one_storm():
    sevs = [storm_severity("HU", km) for km in (100.0, 750.0, 3000.0)]
    assert sevs == sorted(sevs, reverse=True)


# ── geography ─────────────────────────────────────────────────────────────────
def test_a_storm_over_the_island_carries_exact_coordinates():
    """alert_event coordinates are what the dashboard map renders directly — unlike
    events, which it can only place via a linked asset or municipality."""
    alert = nhc_alert(_event(latitudeNumeric=18.2, longitudeNumeric=-66.4))
    assert alert.coord_confidence == "exact"
    assert alert.latitude == pytest.approx(18.2)
    assert alert.longitude == pytest.approx(-66.4)


def test_a_storm_still_at_sea_reports_unknown_rather_than_clamping():
    """alert_event bounds lat/lon to Puerto Rico, so an approaching centre at 64W is out
    of range. Same treatment the seismic promoter gives an offshore epicentre — a
    misleading on-land point would be worse than none."""
    alert = nhc_alert(_event(latitudeNumeric=17.4, longitudeNumeric=-64.2))
    assert alert.coord_confidence == "unknown"
    assert alert.latitude is None and alert.longitude is None
    jsonschema.validate(alert.model_dump(), ALERT_SCHEMA)


def test_distance_to_the_island_is_stated_in_the_title():
    alert = nhc_alert(_event(latitudeNumeric=18.2, longitudeNumeric=-66.4))
    assert "km from Puerto Rico" in alert.source_title
    assert "Hurricane" in alert.source_title and "Bertha" in alert.source_title


# ── identity ──────────────────────────────────────────────────────────────────
def test_alert_id_matches_the_schema_pattern():
    alert = nhc_alert(_event())
    assert re.match(ALERT_ID_PATTERN, alert.alert_id), alert.alert_id
    assert NHC_MARKER in alert.alert_id
    assert "al052026" in alert.alert_id


def test_alert_id_is_stable_for_the_same_advisory():
    assert nhc_alert(_event()).alert_id == nhc_alert(_event()).alert_id


def test_successive_advisories_get_distinct_alerts():
    """They are distinct published positions; together they are the track."""
    a = nhc_alert(_event())
    b = nhc_alert(_event(publicAdvisory={
        "advNum": "015", "issuance": "2026-08-02T09:00:00.000Z", "url": "https://x"}))
    assert a.alert_id != b.alert_id


def test_alert_records_that_this_is_a_forecast_not_an_issued_warning():
    """NHC publishes positions; NWS issues watches and warnings. Conflating them would
    overstate what this alert means."""
    notes = nhc_alert(_event()).validation_notes
    assert "NOT an issued NWS watch or warning" in notes
    assert "ingest_nws_alerts" in notes


# ── robustness ────────────────────────────────────────────────────────────────
def test_empty_and_none_inputs():
    assert nhc_alerts([]) == []
    assert nhc_alerts(None) == []


def test_event_without_coordinates_still_alerts():
    event = _event()
    event.pop("lat"), event.pop("lon")
    alert = nhc_alert(event)
    assert alert is not None
    assert alert.coord_confidence == "unknown"
    jsonschema.validate(alert.model_dump(), ALERT_SCHEMA)


def test_every_classification_the_ingest_can_emit_yields_a_valid_alert():
    for code in ("TD", "TS", "HU", "MH", "PTC", "STD", "STS", "PC", "LO", "DB"):
        alert = nhc_alert(_event(classification=code))
        assert alert is not None, code
        jsonschema.validate(alert.model_dump(), ALERT_SCHEMA)
