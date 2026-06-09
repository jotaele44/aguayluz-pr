import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_usgs_levels import merge, reservoir_site_nos, rows_from_doc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DV_FIXTURE = ROOT / "tests" / "fixtures" / "usgs_dv_sample.json"
SCHEMA = json.loads((ROOT / "schemas" / "monitoring_reading.schema.json").read_text())


def _rows():
    return rows_from_doc(json.loads(DV_FIXTURE.read_text()))


def test_parses_both_elevation_datums_without_collision():
    rows = _rows()
    # 7 days x 2 datums (72375 LMSL, 72379 PRD2002) = 14, all distinct.
    assert len(rows) == 14
    assert len({r["reading_id"] for r in rows}) == 14
    assert {r["parameter_code"] for r in rows} == {"72375", "72379"}


def test_rows_link_to_usgs_asset_and_flag_provisional():
    r = _rows()[0]
    assert r["asset_id"] == "USGS_50059000"
    assert r["metric"] == "reservoir_elevation" and r["unit"] == "ft"
    assert r["provisional"] is True
    assert r["evidence_tier"] == "T1" and r["confidence"] == 75  # T1 80 - 5 provisional


def test_rows_validate_against_monitoring_reading_schema():
    import re

    req = set(SCHEMA["required"])
    allowed = set(SCHEMA["properties"])
    enums = {k: set(v["enum"]) for k, v in SCHEMA["properties"].items() if "enum" in v}
    pat = re.compile(SCHEMA["properties"]["reading_id"]["pattern"])
    for r in _rows():
        assert req <= set(r) and set(r) <= allowed
        for k, choices in enums.items():
            if k in r:
                assert r[k] in choices
        assert pat.match(r["reading_id"])
        assert isinstance(r["value"], (int, float))
        assert 0 <= r["confidence"] <= 100


def test_skips_no_data_sentinels():
    doc = {
        "value": {"timeSeries": [{
            "sourceInfo": {"siteCode": [{"value": "50027100"}]},
            "variable": {"variableCode": [{"value": "00060"}], "unit": {"unitCode": "ft3/s"}},
            "values": [{"value": [
                {"value": "-999999", "qualifiers": ["P"], "dateTime": "2026-06-01T00:00:00.000"},
                {"value": "12.5", "qualifiers": ["A"], "dateTime": "2026-06-02T00:00:00.000"},
            ]}],
        }]}
    }
    rows = rows_from_doc(doc)
    assert len(rows) == 1
    assert rows[0]["value"] == 12.5
    assert rows[0]["metric"] == "streamflow"
    assert rows[0]["provisional"] is False  # 'A' approved, not 'P'


def test_merge_idempotent_by_reading_id():
    rows = _rows()
    once = merge([], rows)
    twice = merge(once, rows)
    assert len(once) == len(twice) == 14


def test_reservoir_site_nos_from_assets(tmp_path):
    assets = tmp_path / "a.jsonl"
    assets.write_text(
        json.dumps({"asset_id": "USGS_50059000", "asset_type": "water"}) + "\n"
        + json.dumps({"asset_id": "PWR00001", "asset_type": "power"}) + "\n"
        + json.dumps({"asset_id": "WTR_9", "asset_type": "water"}) + "\n"
    )
    assert reservoir_site_nos(assets) == ["50059000"]  # only USGS_ water rows
