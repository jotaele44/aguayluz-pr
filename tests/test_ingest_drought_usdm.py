"""Tests for the USDM drought ingester (scripts/ingest_drought_usdm.py). No network."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_drought_usdm import (  # noqa: E402
    PR_MUNICIPIO_FIPS,
    build_asset,
    build_reading,
    dominant_class,
    parse_rows,
)

ROOT = Path(__file__).resolve().parents[1]
READING_SCHEMA = json.loads((ROOT / "schemas" / "monitoring_reading.schema.json").read_text())
ASSET_SCHEMA = json.loads((ROOT / "schemas" / "utility_asset.schema.json").read_text())
FIXTURES = ROOT / "tests" / "fixtures"


def _sample_rows():
    return parse_rows((FIXTURES / "usdm_drought_sample.csv").read_text())


# ── municipio table ─────────────────────────────────────────────────────────
def test_all_78_municipios_have_a_unique_fips():
    assert len(PR_MUNICIPIO_FIPS) == 78
    assert len(set(PR_MUNICIPIO_FIPS.values())) == 78


# ── dominant_class: cumulative "at least this band" percentages -> worst nonzero band
def test_dominant_class_picks_worst_nonzero_band():
    row = {"None": "0.00", "D0": "100.00", "D1": "58.45", "D2": "12.30", "D3": "0.00", "D4": "0.00"}
    assert dominant_class(row) == (2, "D2")


def test_dominant_class_no_drought_designation():
    row = {"None": "100.00", "D0": "0.00", "D1": "0.00", "D2": "0.00", "D3": "0.00", "D4": "0.00"}
    assert dominant_class(row) == (-1, "None")


def test_dominant_class_handles_thousands_separators():
    # The state-level endpoint (area in sq mi, not percent) emits comma-grouped numbers;
    # dominant_class must not choke even though the county/percent endpoint never does.
    row = {"None": "204.86", "D0": "3,234.78", "D1": "1,853.13", "D2": "0.00", "D3": "0.00", "D4": "0.00"}
    assert dominant_class(row) == (1, "D1")


# ── build_reading ────────────────────────────────────────────────────────────
def test_build_reading_matches_schema():
    rows = _sample_rows()
    reading = build_reading(rows[0])
    assert reading is not None
    assert reading["metric"] == "drought_category"
    assert reading["site_no"] == "72001"
    assert reading["asset_id"] == "USDM_72001"
    assert reading["parameter_code"] == "D2"
    assert reading["value"] == 2.0
    assert reading["observed_date"] == "2024-02-06"
    jsonschema.validate(reading, READING_SCHEMA)


def test_build_reading_encodes_no_drought_as_minus_one():
    rows = _sample_rows()
    san_juan = next(r for r in rows if r["FIPS"] == "72127")
    reading = build_reading(san_juan)
    assert reading["value"] == -1.0
    assert reading["parameter_code"] == "None"
    jsonschema.validate(reading, READING_SCHEMA)


def test_build_reading_rejects_unknown_fips():
    assert build_reading({"FIPS": "99999", "County": "Nowhere", "MapDate": "20240206",
                           "ValidStart": "2024-02-06", "D0": "0", "D1": "0", "D2": "0",
                           "D3": "0", "D4": "0"}) is None


# ── build_asset ──────────────────────────────────────────────────────────────
def test_build_asset_uses_municipio_centroid_and_matches_schema():
    geo = {"Adjuntas": {"name": "Adjuntas", "lat": 18.181611, "lon": -66.758165}}
    asset = build_asset("72001", "Adjuntas", geo)
    assert asset["asset_id"] == "USDM_72001"
    assert asset["asset_type"] == "water" and asset["asset_subtype"] == "drought_monitoring_area"
    assert asset["lat"] == 18.181611 and asset["geometry_type"] == "polygon"
    jsonschema.validate(asset, ASSET_SCHEMA)


def test_build_asset_without_centroid_has_no_coords():
    asset = build_asset("72001", "Adjuntas", geo={})
    assert "lat" not in asset and asset["geometry_type"] == "unknown"
    jsonschema.validate(asset, ASSET_SCHEMA)
