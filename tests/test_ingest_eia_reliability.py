import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_eia_reliability import merge_assets, merge_readings, parse_rows  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "eia861_reliability_sample.csv"
MR_SCHEMA = json.loads((ROOT / "schemas" / "monitoring_reading.schema.json").read_text())
UA_SCHEMA = json.loads((ROOT / "schemas" / "utility_asset.schema.json").read_text())


def test_parses_only_pr_utilities():
    assets, readings = parse_rows(FIXTURE)
    # PREPA (15497) + LUMA (15497 is PREPA; LUMA row also 15497) — TX utility excluded.
    util_ids = {a["asset_id"] for a in assets}
    assert util_ids == {"EIA_UTIL_15497"}  # all PR rows share utility 15497; TX dropped
    assert all(r["asset_id"] == "EIA_UTIL_15497" for r in readings)


def test_readings_carry_saidi_saifi_values():
    _, readings = parse_rows(FIXTURE)
    by = {(r["observed_date"][:4], r["parameter_code"]): r for r in readings}
    assert by[("2019", "SAIDI_woMED")]["value"] == 708.03
    assert by[("2019", "SAIFI_woMED")]["value"] == 4.79
    assert by[("2020", "SAIDI_woMED")]["value"] == 778.21
    # With-MED present only for the 2022 LUMA row
    assert by[("2022", "SAIDI_wMED")]["value"] == 1850.5
    # 2019/2020 With-MED are "." -> skipped
    assert ("2019", "SAIDI_wMED") not in by
    r = by[("2019", "SAIDI_woMED")]
    assert r["metric"] == "reliability" and r["unit"] == "minutes/year"
    assert r["reading_id"] == "AYL_RDG_20191231_15497_SAIDI_woMED"


def test_readings_validate_against_monitoring_reading_schema():
    import re

    _, readings = parse_rows(FIXTURE)
    req = set(MR_SCHEMA["required"])
    allowed = set(MR_SCHEMA["properties"])
    enums = {k: set(v["enum"]) for k, v in MR_SCHEMA["properties"].items() if "enum" in v}
    pat = re.compile(MR_SCHEMA["properties"]["reading_id"]["pattern"])
    for r in readings:
        assert req <= set(r) and set(r) <= allowed
        for k, choices in enums.items():
            if k in r:
                assert r[k] in choices
        assert pat.match(r["reading_id"])


def test_utility_asset_is_schema_valid():
    assets, _ = parse_rows(FIXTURE)
    req = set(UA_SCHEMA["required"])
    allowed = set(UA_SCHEMA["properties"])
    enums = {k: set(v["enum"]) for k, v in UA_SCHEMA["properties"].items() if "enum" in v}
    a = assets[0]
    assert req <= set(a) and set(a) <= allowed
    assert a["asset_type"] == "power" and a["asset_subtype"] == "utility_system"
    assert a["geometry_type"] == "unknown"  # system-wide, not a point
    for k, choices in enums.items():
        if k in a:
            assert a[k] in choices


def test_merge_helpers_idempotent_and_scoped():
    assets, readings = parse_rows(FIXTURE)
    other_asset = {"asset_id": "USGS_50059000", "asset_type": "water"}
    merged_a = {a["asset_id"]: a for a in merge_assets([other_asset], assets)}
    assert "USGS_50059000" in merged_a and "EIA_UTIL_15497" in merged_a  # preserved + added
    once = merge_readings([], readings)
    twice = merge_readings(once, readings)
    assert len(once) == len(twice)  # idempotent by reading_id
