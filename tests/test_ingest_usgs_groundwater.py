"""Tests for the USGS groundwater ingester (scripts/ingest_usgs_groundwater.py)."""

import json
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_usgs_groundwater import (  # noqa: E402
    build_assets,
    build_readings,
    merge_assets,
)
from ingest_usgs_water import load_municipios, parse_rdb  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "tests" / "fixtures" / "usgs_gw_sites_sample.rdb"
LEVELS = ROOT / "tests" / "fixtures" / "usgs_gw_levels_sample.json"
ASSET_SCHEMA = json.loads((ROOT / "schemas" / "utility_asset.schema.json").read_text())
READING_SCHEMA = json.loads((ROOT / "schemas" / "monitoring_reading.schema.json").read_text())
MUNIS = load_municipios(ROOT / "data" / "geo" / "pr_municipios.geojson")


def _assets():
    return build_assets(parse_rdb(SITES.read_text()), MUNIS)


def test_assets_use_distinct_gw_prefix_and_subtype():
    rows = _assets()
    assert len(rows) == 3
    assert all(r["asset_id"].startswith("USGSGW_") for r in rows)
    assert all(r["asset_type"] == "water" and r["asset_subtype"] == "groundwater_well" for r in rows)


def test_out_of_bounds_well_gets_no_coords():
    rows = {r["asset_id"]: r for r in _assets()}
    inb = rows["USGSGW_175930066120001"]
    assert inb["lat"] == 18.021 and inb["geometry_type"] == "point"
    off = rows["USGSGW_175030066450001"]  # lat 17.503, below the 17.7 bound
    assert "lat" not in off and off["geometry_type"] == "unknown"


def test_assets_validate_against_schema():
    for r in _assets():
        jsonschema.validate(r, ASSET_SCHEMA)


def test_readings_are_depth_to_water_metric():
    rows = build_readings([json.loads(LEVELS.read_text())])
    assert len(rows) == 14
    r = rows[0]
    assert r["metric"] == "groundwater_level"
    assert r["parameter_code"] == "72019"
    assert r["asset_id"] == "USGSGW_175930066120001"
    assert r["reading_id"].startswith("AYL_RDG_") and r["reading_id"].endswith("_gw")
    for row in rows:
        jsonschema.validate(row, READING_SCHEMA)


def test_gw_merge_preserves_other_assets_replaces_gw():
    existing = [
        {"asset_id": "USGS_50059000", "asset_type": "water"},   # surface — must survive
        {"asset_id": "PWR_1", "asset_type": "power"},           # power — must survive
        {"asset_id": "USGSGW_175930066120001", "confidence": 1},  # stale GW — replaced
    ]
    out = {r["asset_id"]: r for r in merge_assets(existing, _assets())}
    assert "USGS_50059000" in out and "PWR_1" in out
    assert out["USGSGW_175930066120001"]["confidence"] == 80  # freshly built


def test_missing_levels_yields_no_readings():
    assert build_readings([{"value": {"timeSeries": []}}]) == []
    assert build_readings([{}]) == []
