"""scripts/ingest_usgs_peaks.py — USGS annual peak streamflow and stage.

Every built row is validated against the real schemas/monitoring_reading.schema.json.

Fixture note: `usgs_peaks_pr.json` is a REAL capture from
api.waterdata.usgs.gov/ogcapi/v0/collections/peaks, trimmed to eleven features chosen to
cover the cases that matter — the Hurricane Maria record peak, the same-day
max-stage/stage-at-peak-discharge pair, estimated and historic peaks, a regulated basin,
and the 1899 row that opens the record.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ingest_usgs_peaks import (  # noqa: E402
    PEAK_METRICS,
    asset_id_for,
    build_readings,
    merge_readings,
)

FIXTURES = REPO / "tests" / "fixtures"
READING_SCHEMA = json.loads((REPO / "schemas" / "monitoring_reading.schema.json").read_text())


def _doc() -> dict:
    return json.loads((FIXTURES / "usgs_peaks_pr.json").read_text())


def _rows() -> list[dict]:
    return build_readings(_doc())[0]


def _synthetic(**props) -> dict:
    base = {
        "monitoring_location_id": "USGS-50055000",
        "parameter_code": "00060",
        "value": "24300",
        "unit_of_measure": "ft^3/s",
        "time": "1994-09-20",
        "water_year": 1994, "year": 1994, "month": 9, "day": 20,
        "time_of_day": None,
        "qualifier": None,
    }
    base.update(props)
    return {"type": "Feature", "properties": base}


def _fc(*feats) -> dict:
    return {"type": "FeatureCollection", "features": list(feats)}


# ── schema + identity ─────────────────────────────────────────────────────────
def test_build_readings_matches_schema_and_id_pattern():
    rows = _rows()
    assert rows
    pattern = READING_SCHEMA["properties"]["reading_id"]["pattern"]
    for row in rows:
        jsonschema.validate(row, READING_SCHEMA)
        assert re.match(pattern, row["reading_id"]), row["reading_id"]


def test_both_stage_values_for_one_day_survive():
    """The bug this id scheme exists to prevent.

    USGS publishes two stage rows for water year 1996 at site 50055225, on the SAME day:
    GHNOTASSCPKQ (the year's maximum stage) at 30.10 ft and NOTMAXGH (the stage that
    accompanied the peak discharge) at 23.89 ft. Six feet apart, both true. An id keyed on
    site + parameter + water year + date alone collapses them and deletes the higher one.
    """
    stage = sorted(r["value"] for r in _rows()
                   if r["site_no"] == "50055225" and r["metric"] == "gage_height")
    assert stage == [pytest.approx(23.89), pytest.approx(30.10)]


def test_identical_rows_are_collapsed_and_counted():
    rows, skipped = build_readings(_fc(_synthetic(), _synthetic()))
    assert len(rows) == 1 and skipped["duplicate"] == 1


def test_reading_id_is_stable_when_only_the_value_changes():
    """A USGS revision must replace the peak, not add a second one for the same year."""
    first, _ = build_readings(_fc(_synthetic(value="24300")))
    later, _ = build_readings(_fc(_synthetic(value="24500")))
    assert first[0]["reading_id"] == later[0]["reading_id"]
    merged = merge_readings(first, later)
    assert len(merged) == 1 and merged[0]["value"] == pytest.approx(24500)


def test_reading_id_carries_the_water_year():
    row = build_readings(_fc(_synthetic()))[0][0]
    assert ".wy1994" in row["reading_id"]


# ── metric mapping ────────────────────────────────────────────────────────────
def test_parameter_codes_map_onto_the_closed_metric_enum():
    allowed = set(READING_SCHEMA["properties"]["metric"]["enum"])
    assert set(PEAK_METRICS.values()) <= allowed
    assert PEAK_METRICS == {"00060": "streamflow", "00065": "gage_height"}
    assert {r["metric"] for r in _rows()} == {"streamflow", "gage_height"}


def test_unmapped_parameter_is_counted_not_coerced_to_other():
    """A mislabelled metric is worse than an absent row — the same principle the NEON
    column fix established."""
    rows, skipped = build_readings(_fc(_synthetic(parameter_code="00045")))
    assert rows == [] and skipped["unmapped_parameter"] == 1


def test_units_come_from_the_data():
    units = {(r["metric"], r["unit"]) for r in _rows()}
    assert ("streamflow", "ft^3/s") in units
    assert ("gage_height", "ft") in units
    assert all(r["unit"] for r in _rows())


# ── qualifiers ────────────────────────────────────────────────────────────────
def test_estimated_peak_is_flagged_but_kept():
    """An estimated 1964 peak is still the best record of that flood."""
    rows = [r for r in _rows() if "ESTIMATED" in r["source_ref"]]
    assert rows
    for row in rows:
        assert row["review_status"] == "needs_review"


def test_context_qualifiers_do_not_trigger_review():
    """REGULATED, HISTORIC and EVENT describe the basin or the flood, not the value's
    fidelity — flagging them would mark a third of the record for no reason."""
    for qualifier in (["REGULATED"], ["HISTORIC"], ["EVENT"], ["URBAN"], ["REVISED"]):
        row = build_readings(_fc(_synthetic(qualifier=qualifier)))[0][0]
        assert row["review_status"] == "accepted", qualifier
        assert qualifier[0] in row["source_ref"]


def test_value_caveat_qualifiers_trigger_review():
    for qualifier in (["ESTIMATED"], ["GREATERTHAN"], ["LESSTHAN"],
                      ["MAXDAILYMEAN"], ["NOTMAXGH"]):
        row = build_readings(_fc(_synthetic(qualifier=qualifier)))[0][0]
        assert row["review_status"] == "needs_review", qualifier
        assert row["confidence"] < build_readings(_fc(_synthetic()))[0][0]["confidence"]


def test_qualifier_case_is_normalised():
    row = build_readings(_fc(_synthetic(qualifier=["estimated"])))[0][0]
    assert row["review_status"] == "needs_review"


# ── content ───────────────────────────────────────────────────────────────────
def test_the_maria_peak_is_the_record():
    """284,000 ft3/s at Rio Grande de Arecibo on 2017-09-20 — a sanity check that the
    baseline this vector exists to provide is actually in it."""
    flow = [r for r in _rows() if r["metric"] == "streamflow"]
    top = max(flow, key=lambda r: r["value"])
    assert top["value"] == pytest.approx(284000)
    assert top["observed_date"] == "2017-09-20"
    assert top["site_no"] == "50035000"


def test_the_record_reaches_back_past_1900():
    assert min(r["observed_date"] for r in _rows()) < "1900"


def test_source_ref_states_the_water_year():
    for row in _rows():
        assert "annual maximum for water year" in row["source_ref"]


def test_peaks_are_never_provisional():
    """An annual peak is published once the water year closes and is reviewed."""
    assert all(r["provisional"] is False for r in _rows())


# ── asset linkage ─────────────────────────────────────────────────────────────
def test_readings_reference_the_assets_another_ingest_maintains():
    """This script emits no assets: ingest_usgs_water.py owns these USGS_* rows, and
    re-emitting them would fight its whole-prefix merge."""
    assert asset_id_for("50055000") == "USGS_50055000"
    assert all(r["asset_id"].startswith("USGS_") for r in _rows())
    src = (REPO / "scripts" / "ingest_usgs_peaks.py").read_text()
    assert "utility_assets" not in src


# ── refusals ──────────────────────────────────────────────────────────────────
def test_blank_and_unparseable_values_are_skipped():
    rows, skipped = build_readings(_fc(_synthetic(value=""), _synthetic(value="--")))
    assert rows == [] and skipped["no_value"] == 2


def test_undated_peak_is_skipped():
    feat = _synthetic(time="")
    for k in ("year", "month", "day"):
        del feat["properties"][k]
    rows, skipped = build_readings(_fc(feat))
    assert rows == [] and skipped["no_date"] == 1


def test_unitless_peak_is_skipped():
    rows, skipped = build_readings(_fc(_synthetic(unit_of_measure="")))
    assert rows == [] and skipped["no_unit"] == 1


# ── merge ─────────────────────────────────────────────────────────────────────
def test_merges_are_idempotent():
    rows = _rows()
    assert merge_readings(merge_readings([], rows), rows) == merge_readings([], rows)


def test_merge_preserves_rows_from_other_sites():
    existing = [{"reading_id": "AYL_RDG_20200101_OTHER_x", "asset_id": "USGS_1",
                 "observed_date": "2020-01-01"}]
    merged = merge_readings(existing, _rows())
    assert "AYL_RDG_20200101_OTHER_x" in {r["reading_id"] for r in merged}


# ── CLI ───────────────────────────────────────────────────────────────────────
def test_offline_run_writes_valid_output(tmp_path):
    out = tmp_path / "peaks.jsonl"
    cmd = [sys.executable, str(REPO / "scripts" / "ingest_usgs_peaks.py"),
           "--src", str(FIXTURES / "usgs_peaks_pr.json"), "--out", str(out)]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    assert rows
    for row in rows:
        jsonschema.validate(row, READING_SCHEMA)

    before = out.read_bytes()
    assert subprocess.run(cmd, cwd=REPO, capture_output=True, text=True).returncode == 0
    assert out.read_bytes() == before
