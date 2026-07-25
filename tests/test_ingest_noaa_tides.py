"""Tests for the NOAA CO-OPS tides ingester (scripts/ingest_noaa_tides.py)."""

import json
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_noaa_tides import (  # noqa: E402
    _station_meta,
    build_asset,
    build_readings,
    merge_assets,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "noaa_tides_sample.json"
ASSET_SCHEMA = json.loads((ROOT / "schemas" / "utility_asset.schema.json").read_text())
READING_SCHEMA = json.loads((ROOT / "schemas" / "monitoring_reading.schema.json").read_text())


def _doc():
    return json.loads(SAMPLE.read_text())


def test_asset_is_tide_gauge_with_coords():
    a = build_asset(_station_meta(_doc()))
    assert a["asset_id"] == "NOAA_9755371"
    assert a["asset_type"] == "water" and a["asset_subtype"] == "tide_gauge"
    assert a["operator"] == "NOAA CO-OPS"
    assert a["lat"] == 18.4592 and a["geometry_type"] == "point"
    jsonschema.validate(a, ASSET_SCHEMA)


def test_out_of_bounds_station_gets_no_coords():
    doc = {"metadata": {"id": "9999999", "name": "Offshore Buoy", "lat": "17.40", "lon": "-66.5"}, "data": []}
    a = build_asset(_station_meta(doc))
    assert "lat" not in a and a["geometry_type"] == "unknown"
    jsonschema.validate(a, ASSET_SCHEMA)


def test_readings_are_daily_max_coastal_water_level():
    rows = build_readings(_doc())
    # 14 days in the fixture -> one daily-max reading each.
    assert len(rows) == 14
    assert all(r["metric"] == "coastal_water_level" for r in rows)
    assert all(r["asset_id"] == "NOAA_9755371" for r in rows)
    last = rows[-1]
    assert last["observed_date"] == "2026-01-14"
    assert last["value"] == 0.81  # the spiked last-day maximum
    for r in rows:
        jsonschema.validate(r, READING_SCHEMA)


def test_daily_max_picks_highest_intraday_value():
    doc = {"metadata": {"id": "9755371", "name": "X", "lat": "18.4", "lon": "-66.1"},
           "data": [
               {"t": "2026-02-01 00:00", "v": "0.20"},
               {"t": "2026-02-01 12:00", "v": "0.55"},   # the day's max
               {"t": "2026-02-01 18:00", "v": "0.30"},
           ]}
    rows = build_readings(doc)
    assert len(rows) == 1 and rows[0]["value"] == 0.55


def test_tide_merge_preserves_other_assets_replaces_noaa():
    existing = [
        {"asset_id": "USGS_50059000", "asset_type": "water"},
        {"asset_id": "NOAA_9755371", "confidence": 1},
    ]
    fresh = build_asset(_station_meta(_doc()))
    out = {r["asset_id"]: r for r in merge_assets(existing, [fresh])}
    assert "USGS_50059000" in out
    assert out["NOAA_9755371"]["confidence"] == 80  # replaced with freshly built
