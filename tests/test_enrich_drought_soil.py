"""Tests for the NRCS soil enrichment pass (scripts/enrich_drought_soil.py). No network."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from enrich_drought_soil import (  # noqa: E402
    _needs_enrichment,
    merge_soil_onto_asset,
    parse_muaggatt_response,
    parse_mukey_response,
)

ROOT = Path(__file__).resolve().parents[1]
ASSET_SCHEMA = json.loads((ROOT / "schemas" / "utility_asset.schema.json").read_text())


def _base_asset(**over) -> dict:
    base = {
        "asset_id": "USDM_72001", "asset_name": "Adjuntas (USDM drought monitoring area)",
        "asset_type": "water", "asset_subtype": "drought_monitoring_area",
        "operator": "NDMC/USDM (NOAA/USDA partnership)", "municipality": "Adjuntas",
        "lat": 18.181611, "lon": -66.758165, "geometry_type": "polygon", "status": "active",
        "source_ref": "USDM Data Services CountyStatistics API", "evidence_tier": "T1",
        "confidence": 80, "review_status": "accepted",
    }
    base.update(over)
    return base


# ── parse_mukey_response ──────────────────────────────────────────────────────
def test_parse_mukey_response_reads_first_row():
    assert parse_mukey_response([["326812"]]) == "326812"


def test_parse_mukey_response_none_when_point_misses_every_mapunit():
    assert parse_mukey_response([]) is None
    assert parse_mukey_response([[None]]) is None


# ── parse_muaggatt_response: keyed by its own mukey column, order-independent ──
def test_parse_muaggatt_response_keys_by_mukey_regardless_of_row_order():
    rows = [
        ["326914", "Some Series", "Well drained", 18.2, "B"],
        ["326812", "Humatas clay, 40 to 60 percent slopes", "Well drained", 23.74, "C"],
    ]
    out = parse_muaggatt_response(rows)
    assert set(out) == {"326914", "326812"}
    assert out["326812"]["muname"] == "Humatas clay, 40 to 60 percent slopes"
    assert out["326812"]["aws0150wta"] == 23.74
    assert out["326914"]["hydgrpdcd"] == "B"


def test_parse_muaggatt_response_skips_rows_with_no_mukey():
    assert parse_muaggatt_response([[None, "x", "y", 1.0, "A"]]) == {}


# ── merge_soil_onto_asset ─────────────────────────────────────────────────────
def test_merge_writes_all_fields_and_validates():
    asset = _base_asset()
    attrs = {
        "mukey": "326812", "muname": "Humatas clay, 40 to 60 percent slopes",
        "drclassdcd": "Well drained", "aws0150wta": 23.74, "hydgrpdcd": "C",
    }
    changed = merge_soil_onto_asset(asset, "326812", attrs)
    assert changed is True
    assert asset["soil_mukey"] == "326812"
    assert asset["soil_series_name"] == "Humatas clay, 40 to 60 percent slopes"
    assert asset["soil_drainage_class"] == "Well drained"
    assert asset["soil_awc_cm"] == 23.74
    assert asset["soil_hydrologic_group"] == "C"
    jsonschema.validate(asset, ASSET_SCHEMA)


def test_merge_returns_false_when_point_has_no_mukey():
    asset = _base_asset()
    assert merge_soil_onto_asset(asset, None, None) is False
    assert "soil_mukey" not in asset
    jsonschema.validate(asset, ASSET_SCHEMA)


def test_merge_writes_mukey_even_when_muaggatt_lookup_failed():
    """A mukey with no matching muaggatt row (rare, but the join could miss one)
    still records the point's mukey rather than discarding it silently."""
    asset = _base_asset()
    changed = merge_soil_onto_asset(asset, "326812", None)
    assert changed is True
    assert asset["soil_mukey"] == "326812"
    assert "soil_series_name" not in asset
    jsonschema.validate(asset, ASSET_SCHEMA)


# ── _needs_enrichment ─────────────────────────────────────────────────────────
def test_needs_enrichment_true_for_fresh_drought_area_asset_with_coords():
    assert _needs_enrichment(_base_asset()) is True


def test_needs_enrichment_false_once_already_enriched():
    assert _needs_enrichment(_base_asset(soil_mukey="326812")) is False


def test_needs_enrichment_false_for_non_drought_asset_types():
    assert _needs_enrichment(_base_asset(asset_subtype="tide_gauge")) is False


def test_needs_enrichment_false_without_coordinates():
    asset = _base_asset()
    del asset["lat"]
    del asset["lon"]
    assert _needs_enrichment(asset) is False
