"""aguayluz.alert_promotion.drought — USDM drought + NCEI precipitation-shortfall
readings -> AlertEvents. Every emitted alert is validated against
schemas/alert_event.schema.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema

from aguayluz.alert_promotion import GENERATED_MARKERS, build_all_alerts, load_geo
from aguayluz.alert_promotion.drought import (
    DROUGHT_ALERT_FLOOR,
    DROUGHT_MARKER,
    PRECIP_MARKER,
    PRECIP_SHORTFALL_FLOOR,
    drought_alerts,
    precipitation_shortfall_alerts,
)
from aguayluz.impact import build_asset_index

REPO = Path(__file__).resolve().parents[1]
ALERT_SCHEMA = json.loads((REPO / "schemas" / "alert_event.schema.json").read_text())
ALERT_ID_PATTERN = ALERT_SCHEMA["properties"]["alert_id"]["pattern"]

GEO = load_geo([{"name": "Adjuntas", "lat": 18.181611, "lon": -66.758165}])
ASSETS = [
    {
        "asset_id": "USDM_72001", "asset_name": "Adjuntas (USDM drought monitoring area)",
        "asset_type": "water", "asset_subtype": "drought_monitoring_area",
        "municipality": "Adjuntas", "lat": 18.181611, "lon": -66.758165,
    },
    {
        "asset_id": "NCEI_RQW00011641", "asset_name": "San Juan L M Marin Intl Ap",
        "asset_type": "water", "asset_subtype": "precipitation_gauge",
        "municipality": "unknown", "lat": 18.4325, "lon": -66.0106,
    },
]


def _drought_reading(**over) -> dict:
    base = {
        "reading_id": "AYL_RDG_20240206_72001_drought", "asset_id": "USDM_72001",
        "site_no": "72001", "metric": "drought_category", "parameter_code": "D2",
        "value": 2.0, "unit": "category", "observed_date": "2024-02-06",
        "source_ref": "USDM CountyStatistics API", "evidence_tier": "T1",
        "confidence": 80, "review_status": "accepted",
    }
    base.update(over)
    return base


def _precip_reading(**over) -> dict:
    base = {
        "reading_id": "AYL_RDG_20240206_RQW00011641_precip90d", "asset_id": "NCEI_RQW00011641",
        "site_no": "RQW00011641", "metric": "precipitation_pct_normal", "parameter_code": "90d",
        "value": 35.0, "unit": "%", "observed_date": "2024-02-06",
        "source_ref": "NOAA NCEI GHCN-Daily", "evidence_tier": "T1",
        "confidence": 80, "review_status": "accepted",
    }
    base.update(over)
    return base


# ── drought_alerts: official USDM band, T1/accepted ────────────────────────
def test_d2_or_worse_produces_a_schema_valid_weather_hazard_alert():
    index = build_asset_index(ASSETS)
    alerts = drought_alerts([_drought_reading()], GEO, index, ASSETS)
    assert len(alerts) == 1
    alert = alerts[0]
    jsonschema.validate(alert.model_dump(), ALERT_SCHEMA)
    assert alert.module_id == "WEATHER_HAZARD"
    assert alert.severity == 2
    assert alert.evidence_tier == "T1"
    assert alert.review_status == "accepted"
    assert alert.municipalities == ["Adjuntas"]
    assert alert.linked_asset_ids == ["USDM_72001"]
    assert DROUGHT_MARKER in alert.alert_id
    assert re.match(ALERT_ID_PATTERN, alert.alert_id)


def test_below_the_floor_produces_no_alert():
    assert DROUGHT_ALERT_FLOOR == 2
    below = _drought_reading(value=1.0, parameter_code="D1")
    assert drought_alerts([below], GEO, build_asset_index(ASSETS), ASSETS) == []


def test_no_drought_designation_produces_no_alert():
    none_reading = _drought_reading(value=-1.0, parameter_code="None")
    assert drought_alerts([none_reading], GEO, build_asset_index(ASSETS), ASSETS) == []


def test_only_the_newest_reading_per_municipio_is_considered():
    older = _drought_reading(reading_id="AYL_RDG_20240130_72001_drought",
                              observed_date="2024-01-30", value=4.0, parameter_code="D4")
    newer = _drought_reading(value=2.0, parameter_code="D2")  # 2024-02-06, later
    alerts = drought_alerts([older, newer], GEO, build_asset_index(ASSETS), ASSETS)
    assert len(alerts) == 1
    assert alerts[0].severity == 2  # the newer D2, not the stale D4


# ── precipitation_shortfall_alerts: corroborating proxy, T2/needs_review ───
def test_shortfall_below_floor_produces_a_needs_review_alert():
    assert PRECIP_SHORTFALL_FLOOR == 50.0
    index = build_asset_index(ASSETS)
    alerts = precipitation_shortfall_alerts([_precip_reading()], GEO, index, ASSETS)
    assert len(alerts) == 1
    alert = alerts[0]
    jsonschema.validate(alert.model_dump(), ALERT_SCHEMA)
    assert alert.module_id == "WEATHER_HAZARD"
    assert alert.evidence_tier == "T2"
    assert alert.review_status == "needs_review"
    assert alert.severity == 1
    assert PRECIP_MARKER in alert.alert_id


def test_precip_at_or_above_floor_produces_no_alert():
    ok = _precip_reading(value=75.0)
    assert precipitation_shortfall_alerts([ok], GEO, build_asset_index(ASSETS), ASSETS) == []


def test_precip_shortfall_ignores_the_30d_window():
    # Only the 90d window is a corroboration signal; a dry 30-day spell alone is common.
    thirty_day = _precip_reading(reading_id="AYL_RDG_20240206_RQW00011641_precip30d",
                                  parameter_code="30d", value=10.0)
    assert precipitation_shortfall_alerts([thirty_day], GEO, build_asset_index(ASSETS), ASSETS) == []


# ── wiring into the registry ─────────────────────────────────────────────────
def test_markers_are_registered_as_generated():
    assert DROUGHT_MARKER in GENERATED_MARKERS
    assert PRECIP_MARKER in GENERATED_MARKERS


def test_build_all_alerts_runs_both_promoters():
    readings = [_drought_reading(), _precip_reading()]
    alerts = build_all_alerts([], readings, GEO, ASSETS)
    markers = {DROUGHT_MARKER, PRECIP_MARKER}
    found = {m for m in markers if any(m in a.alert_id for a in alerts)}
    assert found == markers
