"""scripts/ingest_usgs_samples.py — USGS discrete water-quality samples.

Every built row is validated against the real schemas/*.schema.json.

Fixture note: unlike the NEON manifest/CSV fixtures, `usgs_samples_laguna_cartagena.csv`
is a REAL capture from api.waterdata.usgs.gov/samples-data (keyless), trimmed to eight
representative rows — the well, a non-detect, and chemistry from both surface sites.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ingest_usgs_samples import (  # noqa: E402
    DEFAULT_SITES,
    asset_id_for,
    build_assets,
    build_readings,
    merge_assets,
    merge_readings,
)

FIXTURES = REPO / "tests" / "fixtures"
ASSET_SCHEMA = json.loads((REPO / "schemas" / "utility_asset.schema.json").read_text())
READING_SCHEMA = json.loads((REPO / "schemas" / "monitoring_reading.schema.json").read_text())


def _rows() -> list[dict]:
    import csv
    return list(csv.DictReader((FIXTURES / "usgs_samples_laguna_cartagena.csv").open()))


# ── asset id routing ──────────────────────────────────────────────────────────
def test_site_number_length_picks_the_owning_prefix():
    """A 15-digit site is groundwater (USGSGW_), an 8-digit one surface water (USGS_).

    Getting this wrong either orphans the reading from its asset or collides with
    another ingest's prefix-wide merge.
    """
    assert asset_id_for("180046067053700") == "USGSGW_180046067053700"
    assert asset_id_for("50129899") == "USGS_50129899"


# ── assets ────────────────────────────────────────────────────────────────────
def test_build_assets_matches_schema():
    for row in build_assets(_rows()):
        jsonschema.validate(row, ASSET_SCHEMA)


def test_only_wells_become_assets():
    """Surface-water sites are owned by ingest_usgs_water.py; re-emitting them here
    would fight that script's merge, which replaces the whole USGS_* slice."""
    assets = build_assets(_rows())
    assert [a["asset_id"] for a in assets] == ["USGSGW_180046067053700"]


def test_well_is_flagged_needs_review_with_a_provenance_note():
    """A site whose whole record is decades-old one-off samples is a documented gap,
    not a live feed."""
    well = build_assets(_rows())[0]
    assert well["review_status"] == "needs_review"
    assert "no daily-values" in well["source_ref"]
    assert well["asset_subtype"] == "groundwater_well"


# ── readings ──────────────────────────────────────────────────────────────────
def test_build_readings_matches_schema():
    readings, _ = build_readings(_rows())
    assert readings
    for row in readings:
        jsonschema.validate(row, READING_SCHEMA)


def test_non_detect_is_skipped_not_stored_as_zero():
    """'Not Detected' means below the detection limit, which is not the same as 0."""
    readings, skipped = build_readings(_rows())
    assert skipped["no_value"] == 1
    assert all(r["value"] != 0 or r["unit"] for r in readings)
    assert not any("mbas" in r["reading_id"].lower() for r in readings)


def test_unitless_result_is_skipped():
    """monitoring_reading.unit requires a non-empty string; inventing one would
    mislabel the measurement. Constructed inline — real captures pair blank units
    with non-detects, so this case needs to be made deliberately."""
    header = ",".join([
        "Location_Identifier", "Location_Name", "Location_Type",
        "Location_Latitude", "Location_Longitude", "Activity_StartDate",
        "Result_ResultDetectionCondition", "Result_Characteristic",
        "Result_Measure", "Result_MeasureUnit", "USGSpcode",
    ])
    row = "USGS-50129899,LAGUNA CARTAGENA,Lake,18.012,-67.109,2011-11-16,,Nitrate,0.44,,00618"
    import csv
    import io
    readings, skipped = build_readings(list(csv.DictReader(io.StringIO(header + "\n" + row))))
    assert readings == []
    assert skipped["no_unit"] == 1


def test_reading_id_carries_the_characteristic():
    """One site reports many characteristics on the same day; an id keyed only on
    site+metric+date would collapse them onto a single row."""
    readings, _ = build_readings(_rows())
    same_day = [r for r in readings if r["site_no"] == "50129900" and r["observed_date"] == "2011-11-16"]
    assert len(same_day) > 1
    assert len({r["reading_id"] for r in same_day}) == len(same_day)
    import re
    pattern = READING_SCHEMA["properties"]["reading_id"]["pattern"]
    assert all(re.match(pattern, r["reading_id"]) for r in readings)


def test_units_come_from_the_data_not_a_lookup():
    """The API publishes Result_MeasureUnit per row, so nothing is guessed here."""
    readings, _ = build_readings(_rows())
    units = {r["unit"] for r in readings}
    assert "cfu/100mL" in units      # Enterococcus
    assert "deg C" in units          # water temperature
    assert "uS/cm" in units          # specific conductance
    assert "" not in units


def test_every_reading_maps_to_the_closed_metric_enum():
    readings, _ = build_readings(_rows())
    allowed = set(READING_SCHEMA["properties"]["metric"]["enum"])
    assert {r["metric"] for r in readings} <= allowed
    assert {r["metric"] for r in readings} == {"water_quality"}


def test_parameter_code_preserves_which_property_was_measured():
    """metric collapses everything to water_quality, so parameter_code is what keeps
    conductance distinguishable from enterococcus downstream."""
    readings, _ = build_readings(_rows())
    well = next(r for r in readings if r["site_no"] == "180046067053700")
    assert well["parameter_code"] == "00095"
    assert well["value"] == pytest.approx(2350.0)
    assert well["unit"] == "uS/cm"


# ── merge semantics ───────────────────────────────────────────────────────────
def test_merge_assets_preserves_other_groundwater_wells():
    """The sibling ingest owns 36 monitored USGSGW_ wells; a prefix-wide replace here
    would delete them."""
    existing = [
        {"asset_id": "USGSGW_500001"},
        {"asset_id": "USGS_50129899"},
        {"asset_id": "USGSGW_180046067053700", "asset_name": "stale"},
    ]
    merged = merge_assets(existing, build_assets(_rows()))
    by_id = {r["asset_id"]: r for r in merged}
    assert set(by_id) == {"USGSGW_500001", "USGS_50129899", "USGSGW_180046067053700"}
    assert by_id["USGSGW_180046067053700"]["asset_name"] != "stale"


def test_merges_are_idempotent():
    assets = build_assets(_rows())
    readings, _ = build_readings(_rows())
    assert merge_assets(merge_assets([], assets), assets) == merge_assets([], assets)
    assert merge_readings(merge_readings([], readings), readings) == merge_readings([], readings)


# ── CLI ───────────────────────────────────────────────────────────────────────
def test_default_sites_are_the_laguna_cartagena_basin():
    assert set(DEFAULT_SITES) == {"50129899", "50129900", "180046067053700"}


def test_offline_run_writes_valid_output(tmp_path):
    out = tmp_path / "readings.jsonl"
    assets = tmp_path / "assets.jsonl"
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ingest_usgs_samples.py"),
         "--src", str(FIXTURES / "usgs_samples_laguna_cartagena.csv"),
         "--assets-out", str(assets), "--readings-out", str(out)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    assert rows
    for row in rows:
        jsonschema.validate(row, READING_SCHEMA)
    assert "skipped" in proc.stdout      # drops are reported, never silent
