"""NWPS gauge adapter: material-state revisions, sentinels and raw/normalized separation.

Inputs are the real captures in tests/fixtures/nwps_pr_gauges_sample.json and
tests/fixtures/nwps_gauge_details/ (trimmed to the fields the adapter reads).
"""
import copy
import json
from pathlib import Path

from aguayluz.hazard_adapters import nwps_gauges as adapter
from aguayluz.hazard_plane import HazardFamily, RecordKind, RecordStatus

FIXTURES = Path(__file__).parent / "fixtures"


def _entry(lid):
    gauges = json.loads((FIXTURES / "nwps_pr_gauges_sample.json").read_text())["gauges"]
    return next(g for g in gauges if g["lid"] == lid)


def _detail(lid):
    raw = json.loads((FIXTURES / "nwps_gauge_details" / f"{lid}.json").read_text())
    return adapter.compact_detail(raw)


def test_normalize_keeps_raw_and_normalized_apart():
    record = adapter.normalize(_entry("QUEP4"), _detail("QUEP4"), "HYDROMET:nwps_gauges:abc")
    assert record.family == HazardFamily.HYDROMETEOROLOGY
    assert record.record_kind == RecordKind.OBSERVATION
    assert record.canonical_event_id == "NWPS_GAUGE:QUEP4"
    assert record.record_id.startswith("NWPS_GAUGE:QUEP4:REV:")
    assert record.status == RecordStatus.PROVISIONAL
    assert record.raw_attributes["gauge"]["status"]["observed"]["floodCategory"] == "minor"
    values = record.normalized_values
    assert values["flood_category"] == "minor"
    assert values["thresholds"]["minor"]["stage"] == 644.6
    assert values["usgs_id"] == "50010800"
    # flow is the -999 sentinel upstream: normalized to None, raw left untouched
    assert values["observed_flow"] is None
    assert record.raw_attributes["gauge"]["status"]["observed"]["secondary"] == -999


def test_thresholds_omit_undefined_categories():
    assert adapter.flood_thresholds(_detail("ESPP4")) == {}
    assert set(adapter.flood_thresholds(_detail("AIBP4"))) == {"action", "minor", "moderate", "major"}


def test_placeholder_time_and_sentinels_are_none():
    assert adapter.parse_time("0001-01-01T00:00:00Z") is None
    assert adapter.parse_time("not a time") is None
    assert adapter.clean_number(-999) is None
    assert adapter.clean_number(-9999.0) is None
    assert adapter.clean_number(True) is None
    assert adapter.clean_number(12.5) == 12.5


def test_stage_change_alone_is_not_a_new_revision():
    entry = _entry("AIBP4")
    moved = copy.deepcopy(entry)
    moved["status"]["observed"]["primary"] = entry["status"]["observed"]["primary"] + 0.4
    moved["status"]["observed"]["validTime"] = "2026-10-07T21:00:00Z"
    detail = _detail("AIBP4")
    assert adapter.material_digest(adapter.material_state(entry, detail)) == adapter.material_digest(
        adapter.material_state(moved, detail)
    )


def test_returning_to_an_earlier_state_still_gets_a_distinct_revision_id():
    detail = _detail("AIBP4")
    calm = adapter.material_state(_entry("AIBP4"), detail)
    first = adapter.stable_record_id(calm, None)
    flooded = dict(calm, flood_category="action")
    second = adapter.stable_record_id(flooded, first)
    third = adapter.stable_record_id(calm, second)
    assert len({first, second, third}) == 3


def test_out_of_service_gauge_is_inactive():
    detail = dict(_detail("AIBP4"), inService={"enabled": False, "message": "maintenance"})
    record = adapter.normalize(_entry("AIBP4"), detail, "m")
    assert record.status == RecordStatus.INACTIVE


def test_unknown_category_is_unresolved_not_guessed():
    entry = copy.deepcopy(_entry("AIBP4"))
    entry["status"]["observed"]["floodCategory"] = ""
    record = adapter.normalize(entry, _detail("AIBP4"), "m")
    assert record.status == RecordStatus.UNRESOLVED
