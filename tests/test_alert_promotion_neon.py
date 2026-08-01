"""aguayluz.alert_promotion.neon — NEON publication events -> AlertEvents.

Every emitted alert is validated against the real schemas/alert_event.schema.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from aguayluz.alert_promotion import GENERATED_MARKERS, build_all_alerts
from aguayluz.alert_promotion.neon import NEON_MARKER, neon_alert, neon_alerts

REPO = Path(__file__).resolve().parents[1]
ALERT_SCHEMA = json.loads((REPO / "schemas" / "alert_event.schema.json").read_text())
ALERT_ID_PATTERN = ALERT_SCHEMA["properties"]["alert_id"]["pattern"]


def _record(**over) -> dict:
    base = {
        "event_id": "CUPE_DP4.00130.001_new_month_2026-06",
        "change_type": "new_month",
        "registry_id": "NEON_CUPE_DP4.00130.001",
        "neon_site": "CUPE",
        "site_name": "Río Cupeyes NEON",
        "habitat": "aquatic",
        "lat": 18.11352,
        "lon": -66.98676,
        "product_code": "DP4.00130.001",
        "product_title": "Continuous discharge",
        "latest_month": "2026-06",
        "month_count": 98,
        "latest_release": "RELEASE-2026",
        "release_generated_at": "2026-01-23T00:07:49Z",
        "source_ref": "NEON API v0 /sites/CUPE",
        "source_hash": "a" * 64,
        "evidence_tier": "T1",
        "confidence": 80,
        "detected_at": "2026-07-29T19:00:00Z",
    }
    base.update(over)
    return base


# ── schema conformance ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "change_type",
    ["new_month", "backfilled_month", "new_release", "new_product", "publication_gap"],
)
def test_every_change_type_yields_a_schema_valid_alert(change_type):
    import jsonschema
    alert = neon_alert(_record(change_type=change_type, months_behind=5))
    assert alert is not None
    jsonschema.validate(alert.model_dump(), ALERT_SCHEMA)


def test_alert_id_has_no_dots_despite_the_product_code():
    """alert_id forbids `.`; every NEON product code contains two."""
    alert = neon_alert(_record())
    assert "." not in alert.alert_id
    assert re.match(ALERT_ID_PATTERN, alert.alert_id)
    assert "DP4_00130_001" in alert.alert_id
    assert NEON_MARKER in alert.alert_id


def test_alert_id_is_stable_across_redetection():
    """Anchored on the published month, not the run time, so the merge replaces
    rather than accumulates."""
    first = neon_alert(_record(detected_at="2026-07-01T00:00:00Z"))
    later = neon_alert(_record(detected_at="2026-07-29T00:00:00Z"))
    assert first.alert_id == later.alert_id


# ── module routing ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "product_code,expected",
    [
        ("DP4.00130.001", "HYDRO_OPS"),        # continuous discharge
        ("DP1.20016.001", "HYDRO_OPS"),        # surface-water elevation
        ("DP1.20093.001", "CONTAMINATION"),    # surface-water chemistry
        ("DP1.20033.001", "CONTAMINATION"),    # nitrate
        ("DP1.00045.001", "WEATHER_HAZARD"),   # precipitation
    ],
)
def test_product_routes_to_the_right_module(product_code, expected):
    assert neon_alert(_record(product_code=product_code)).module_id == expected


def test_publication_gap_routes_to_telecom_scada():
    """A station that stopped publishing is telemetry loss at remote infrastructure."""
    alert = neon_alert(_record(change_type="publication_gap", months_behind=6))
    assert alert.module_id == "TELECOM_SCADA"
    assert alert.event_type == "failure"
    assert "6" in alert.validation_notes


def test_unrouted_product_yields_no_alert():
    """Off-mission NEON products must not reach the alert layer.

    NEON publishes ~80 products per site, mostly ecological research. Real upstream
    publications during verification — GUAN plant phenology (DP1.10055.001) and LAJA
    mosquito trapping (DP1.10043.001) — would have raised WEATHER_HAZARD alerts under
    the old habitat-default routing. They are tracked in the availability registry but
    are not water/power signals.
    """
    assert neon_alert(_record(product_code="DP1.10055.001", neon_site="GUAN",
                              habitat="terrestrial")) is None
    assert neon_alert(_record(product_code="DP1.10043.001", neon_site="LAJA",
                              habitat="terrestrial")) is None
    assert neon_alert(_record(product_code="DP1.10058.001")) is None


def test_publication_gap_still_alerts_for_an_unrouted_product():
    """Feed health is about the pipeline, not the product's subject matter."""
    alert = neon_alert(_record(product_code="DP1.10055.001", change_type="publication_gap",
                               months_behind=7))
    assert alert is not None
    assert alert.module_id == "TELECOM_SCADA"


# ── severity ──────────────────────────────────────────────────────────────────
def test_no_publication_alert_is_life_safety_critical():
    """These are operator signals; none may cross the push/SMS threshold."""
    from aguayluz.alert_promotion import CRITICAL_SEVERITY, is_critical
    for change_type in ("new_month", "backfilled_month", "new_release", "new_product",
                        "publication_gap"):
        alert = neon_alert(_record(change_type=change_type, months_behind=12))
        assert alert.severity < CRITICAL_SEVERITY
        assert not is_critical(alert.severity, alert.status)


# ── geography + linkage ───────────────────────────────────────────────────────
def test_alert_carries_site_coordinates_and_municipality():
    alert = neon_alert(_record())
    assert alert.coord_confidence == "exact"
    assert alert.latitude == pytest.approx(18.11352)
    assert alert.municipalities == ["San Germán"]
    assert "NEON_CUPE" in alert.linked_asset_ids
    assert alert.asset_id == "NEON_CUPE"


def test_out_of_bounds_coordinates_are_dropped_not_clamped():
    alert = neon_alert(_record(lat=45.0, lon=-100.0))
    assert alert.latitude is None
    assert alert.longitude is None
    assert alert.coord_confidence == "unknown"


# ── filtering ─────────────────────────────────────────────────────────────────
def test_unknown_change_type_yields_no_alert():
    assert neon_alert(_record(change_type="something_else")) is None


def test_incomplete_record_yields_no_alert():
    assert neon_alert(_record(neon_site="")) is None
    assert neon_alert(_record(product_code="")) is None


def test_neon_alerts_handles_empty_and_none():
    assert neon_alerts([]) == []
    assert neon_alerts(None) == []


# ── registry wiring ───────────────────────────────────────────────────────────
def test_marker_is_registered_for_idempotent_merge():
    assert NEON_MARKER in GENERATED_MARKERS


def test_build_all_alerts_includes_neon_events():
    alerts = build_all_alerts([], None, {}, [], neon_events=[_record()])
    assert [a.alert_id for a in alerts if NEON_MARKER in a.alert_id]


def test_build_all_alerts_without_neon_events_is_unchanged():
    """Existing callers that never pass neon_events must behave exactly as before."""
    assert build_all_alerts([], None, {}, []) == []
