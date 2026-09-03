import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_eia_facility_fuel import merge_assets, merge_readings, parse  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "eia_facility_fuel_sample.csv"
UA = json.loads((ROOT / "schemas" / "utility_asset.schema.json").read_text())
MR = json.loads((ROOT / "schemas" / "monitoring_reading.schema.json").read_text())


def test_parses_pr_plants_only():
    assets, _ = parse(FIXTURE)
    ids = {a["asset_id"] for a in assets}
    assert ids == {"EIA_PLANT_61034", "EIA_PLANT_61014"}  # TX plant excluded


def test_primary_fuel_in_subtype():
    assets = {a["asset_id"]: a for a in parse(FIXTURE)[0]}
    assert assets["EIA_PLANT_61034"]["asset_subtype"] == "generation (Natural Gas)"
    assert assets["EIA_PLANT_61014"]["asset_subtype"] == "generation (Wind)"
    assert assets["EIA_PLANT_61014"]["asset_name"] == "Pattern Santa Isabel LLC"


def test_generation_readings_from_total_rows():
    _, readings = parse(FIXTURE)
    by = {(r["asset_id"], r["observed_date"]): r for r in readings}
    eco = by[("EIA_PLANT_61034", "2017-01-01")]
    assert eco["metric"] == "generation" and eco["value"] == 287145 and eco["unit"] == "MWh"
    assert eco["reading_id"] == "AYL_RDG_20170101_61034_netgen"
    # two months for EcoElectrica, one for Santa Isabel
    assert sum(1 for r in readings if r["asset_id"] == "EIA_PLANT_61034") == 2
    assert sum(1 for r in readings if r["asset_id"] == "EIA_PLANT_61014") == 1


def test_assets_and_readings_validate_against_schemas():
    import re

    assets, readings = parse(FIXTURE)
    for schema, recs, _idfield in ((UA, assets, None), (MR, readings, "reading_id")):
        req = set(schema["required"])
        allowed = set(schema["properties"])
        enums = {k: set(v["enum"]) for k, v in schema["properties"].items() if "enum" in v}
        for r in recs:
            assert req <= set(r) and set(r) <= allowed
            for k, choices in enums.items():
                if k in r:
                    assert r[k] in choices
    pat = re.compile(MR["properties"]["reading_id"]["pattern"])
    assert all(pat.match(r["reading_id"]) for r in readings)


def test_merge_scopes():
    assets, readings = parse(FIXTURE)
    merged = {a["asset_id"]: a for a in merge_assets([{"asset_id": "OSMP_-1", "asset_type": "power"}], assets)}
    assert "OSMP_-1" in merged and "EIA_PLANT_61034" in merged  # OSM preserved, EIA added
    once = merge_readings([], readings)
    assert len(merge_readings(once, readings)) == len(once)  # idempotent
