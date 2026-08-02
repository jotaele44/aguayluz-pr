import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_egrid_emissions import _read_csv, build_readings, merge  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "egrid_pr_plants_sample.csv"
SCHEMA = json.loads((ROOT / "schemas" / "monitoring_reading.schema.json").read_text())
ROWS = _read_csv(FIXTURE)
# pretend HIFLD has 62410 and EIA has 61034 → linkage preference test
PLANT_IDX = {"62410": "HIFLD_PP_62410", "61034": "EIA_PLANT_61034"}


def test_pr_only_and_links_to_existing_plant_assets():
    r = build_readings(ROWS, PLANT_IDX, 65)
    codes = {x["site_no"] for x in r}
    assert "99999" not in codes  # TX excluded
    by = {(x["site_no"], x["parameter_code"]): x for x in r}
    assert by[("62410", "CO2")]["asset_id"] == "HIFLD_PP_62410"   # HIFLD link
    assert by[("61034", "CO2")]["asset_id"] == "EIA_PLANT_61034"  # EIA link
    # plant with no known asset falls back to EIA_PLANT_<code>
    assert by[("61014", "CO2")]["asset_id"] == "EIA_PLANT_61014"


def test_emissions_values_and_metric():
    by = {(x["site_no"], x["parameter_code"]): x for x in build_readings(ROWS, PLANT_IDX, 65)}
    co2 = by[("62410", "CO2")]
    assert co2["metric"] == "emissions" and co2["value"] == 3850000.0
    assert co2["unit"] == "short tons/year"
    assert co2["reading_id"] == "AYL_RDG_20231231_62410_CO2"
    # three params per plant (CO2/NOX/SO2), even when zero (Santa Isabel wind = 0s)
    assert by[("61014", "SO2")]["value"] == 0.0


def test_rows_validate_against_monitoring_reading_schema():
    import re
    rows = build_readings(ROWS, PLANT_IDX, 65)
    req = set(SCHEMA["required"]); allowed = set(SCHEMA["properties"])
    enums = {k: set(v["enum"]) for k, v in SCHEMA["properties"].items() if "enum" in v}
    pat = re.compile(SCHEMA["properties"]["reading_id"]["pattern"])
    assert "emissions" in enums["metric"]
    for r in rows:
        assert req <= set(r) and set(r) <= allowed
        for k, choices in enums.items():
            if k in r:
                assert r[k] in choices
        assert pat.match(r["reading_id"])


def test_merge_idempotent():
    rows = build_readings(ROWS, PLANT_IDX, 65)
    once = merge([], rows)
    assert len(merge(once, rows)) == len(once)
