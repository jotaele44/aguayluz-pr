import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_usgs_levels import (  # noqa: E402
    _rows_from_modern_docs,
    merge,
    reservoir_site_nos,
    rows_from_doc,
)

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


def _modern_feature(
    *,
    statistic_id: str = "00003",
    value: str = "42.5",
    approval_status: str | None = "Approved",
) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "monitoring_location_id": "USGS-50059000",
            "parameter_code": "00060",
            "statistic_id": statistic_id,
            "time": "2026-10-01",
            "value": value,
            "unit_of_measure": "ft^3/s",
            "approvals_status": approval_status,
            "qualifier": None,
        },
    }


def test_modern_daily_prefers_exactly_one_daily_mean_without_identity_change():
    doc = {
        "features": [
            _modern_feature(statistic_id="00001", value="55.0"),
            _modern_feature(statistic_id="00003", value="42.5"),
        ]
    }
    rows = _rows_from_modern_docs([doc])
    assert len(rows) == 1
    row = rows[0]
    assert row["reading_id"] == "AYL_RDG_20261001_50059000_00060"
    assert row["asset_id"] == "USGS_50059000"
    assert row["metric"] == "streamflow"
    assert row["value"] == 42.5
    assert row["unit"] == "ft^3/s"
    assert row["provisional"] is False
    assert "stat 00003" in row["source_ref"]


def test_modern_daily_fails_closed_on_ambiguous_nonmean_statistics():
    doc = {
        "features": [
            _modern_feature(statistic_id="00001", value="55.0"),
            _modern_feature(statistic_id="00002", value="30.0"),
        ]
    }
    with pytest.raises(ValueError, match="ambiguous_daily_statistic"):
        _rows_from_modern_docs([doc])


def test_modern_daily_treats_unknown_or_provisional_approval_as_provisional():
    provisional = _rows_from_modern_docs(
        [{"features": [_modern_feature(approval_status="Provisional")]}]
    )[0]
    unknown = _rows_from_modern_docs(
        [{"features": [_modern_feature(approval_status=None)]}]
    )[0]
    assert provisional["provisional"] is True
    assert unknown["provisional"] is True
    assert provisional["confidence"] == 75
    assert unknown["confidence"] == 75

    singular = _modern_feature(approval_status=None)
    singular["properties"].pop("approvals_status")
    singular["properties"]["approval_status"] = "Approved"
    row = _rows_from_modern_docs([{"features": [singular]}])[0]
    assert row["provisional"] is False


def test_modern_daily_rejects_non_usgs_monitoring_location():
    feature = _modern_feature()
    feature["properties"]["monitoring_location_id"] = "OTHER-50059000"
    with pytest.raises(ValueError, match="unexpected_monitoring_location_id"):
        _rows_from_modern_docs([{"features": [feature]}])


def test_modern_daily_rows_remain_monitoring_schema_valid():
    import re

    row = _rows_from_modern_docs([{"features": [_modern_feature()]}])[0]
    required = set(SCHEMA["required"])
    allowed = set(SCHEMA["properties"])
    enums = {
        key: set(value["enum"])
        for key, value in SCHEMA["properties"].items()
        if "enum" in value
    }
    assert required <= set(row)
    assert set(row) <= allowed
    assert re.compile(SCHEMA["properties"]["reading_id"]["pattern"]).match(
        row["reading_id"]
    )
    for key, choices in enums.items():
        if key in row:
            assert row[key] in choices


def test_modern_daily_detects_statistic_ambiguity_across_pages():
    docs = [
        {"features": [_modern_feature(statistic_id="00001", value="55.0")]},
        {"features": [_modern_feature(statistic_id="00002", value="30.0")]},
    ]
    with pytest.raises(ValueError, match="ambiguous_daily_statistic"):
        _rows_from_modern_docs(docs)



def test_modern_daily_rejects_usgs_site_outside_requested_candidate_set():
    with pytest.raises(ValueError, match="unexpected_monitoring_location"):
        _rows_from_modern_docs(
            [{"features": [_modern_feature()]}],
            allowed_sites={"50027100"},
        )


def test_modern_daily_accepts_requested_candidate_set():
    rows = _rows_from_modern_docs(
        [{"features": [_modern_feature()]}],
        allowed_sites={"50059000"},
    )
    assert [row["site_no"] for row in rows] == ["50059000"]
