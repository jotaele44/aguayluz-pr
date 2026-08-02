"""scripts/ingest_usgs_field_measurements.py — USGS discrete groundwater levels.

Every built row is validated against the real schemas/*.schema.json.

Fixture note: like `usgs_samples_laguna_cartagena.csv` and unlike the NEON fixtures,
`usgs_field_measurements_pr.json` and `usgs_monitoring_locations_pr.json` are REAL
captures from api.waterdata.usgs.gov/ogcapi/v0, trimmed to nine features and the eight
matching sites — the Laguna Cartagena well's two 1985 measurements, a well that also
carries a daily-values series, wells that do not, and both approval states.
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

from ingest_usgs_field_measurements import (  # noqa: E402
    DEFAULT_BBOX,
    DEFAULT_PARAMETER_CODES,
    GW_METRIC,
    _year_slices,
    asset_id_for,
    build_assets,
    build_readings,
    merge_assets,
    merge_readings,
    parse_features,
    parse_locations,
)

FIXTURES = REPO / "tests" / "fixtures"
ASSET_SCHEMA = json.loads((REPO / "schemas" / "utility_asset.schema.json").read_text())
READING_SCHEMA = json.loads((REPO / "schemas" / "monitoring_reading.schema.json").read_text())

WELL = "180046067053700"          # Laguna Cartagena — discrete measurements only
CEMETERY_WELL = "175837066181901"  # a site whose published aquifer_code is null


def _doc() -> dict:
    return json.loads((FIXTURES / "usgs_field_measurements_pr.json").read_text())


def _feats() -> list[dict]:
    return parse_features(_doc())


def _locs() -> dict[str, dict]:
    return parse_locations(json.loads((FIXTURES / "usgs_monitoring_locations_pr.json").read_text()))


def _synthetic(**props) -> dict:
    base = {
        "monitoring_location_id": "USGS-180046067053700",
        "parameter_code": "72019",
        "value": "12.34",
        "unit_of_measure": "ft",
        "time": "2026-01-02T15:00:00+00:00",
        "time_of_day": "15:00:00+00:00",
        "year": 2026, "month": 1, "day": 2,
        "reading_type": "ReferencePrimary",
        "approval_status": "Approved",
        "qualifier": ["Static"],
        "vertical_datum": "NGVD29",
        "observing_procedure": "GW level, calib steel tape",
    }
    base.update(props)
    return {"type": "Feature", "properties": base,
            "geometry": {"type": "Point", "coordinates": [-67.093234, 18.010797]}}


# ── asset id routing / cross-cadence safety ───────────────────────────────────
def test_asset_id_is_a_pure_function_of_the_site_number():
    """No I/O, no lookup into another script's output — see the FM_PREFIX comment."""
    assert asset_id_for(WELL) == f"USGSFM_{WELL}"
    assert asset_id_for("50129899") == "USGSFM_50129899"


def test_daily_groundwater_run_cannot_delete_these_wells():
    """Regression guard, the whole reason for a separate prefix.

    ingest_usgs_groundwater.merge_assets replaces EVERY USGSGW_* row and regenerates only
    wells carrying a daily-values series. Under that prefix, a well whose DV series lapses
    is deleted on the next daily run while this script's readings still point at it.
    """
    from ingest_usgs_groundwater import merge_assets as gw_merge

    ours = build_assets(_feats(), _locs())[0]
    existing = [ours, {"asset_id": "USGSGW_500001", "asset_name": "a monitored well"}]
    survivors = {r["asset_id"] for r in gw_merge(existing, [{"asset_id": "USGSGW_500001"}])}
    assert ours["asset_id"] in survivors


def test_every_reading_points_at_an_asset_this_script_emits():
    """No orphans: the foreign key and the asset id come from the same pure function."""
    readings, _ = build_readings(_feats())
    assets = {a["asset_id"] for a in build_assets(_feats(), _locs())}
    assert {r["asset_id"] for r in readings} <= assets


def test_overlapping_well_still_gets_this_scripts_own_id():
    """A site that also has a USGSGW_ asset is NOT re-pointed at it."""
    readings, _ = build_readings(_feats())
    assert all(r["asset_id"].startswith("USGSFM_") for r in readings)


# ── assets ────────────────────────────────────────────────────────────────────
def test_build_assets_matches_schema():
    for row in build_assets(_feats(), _locs()):
        jsonschema.validate(row, ASSET_SCHEMA)


def test_asset_name_falls_back_when_location_metadata_is_absent():
    """utility_asset.asset_name is required with minLength 1, and field-measurements
    carries no site name — so a missing locations document must not yield an empty one."""
    rows = build_assets(_feats(), None)
    assert rows
    for row in rows:
        assert row["asset_name"].strip()
        jsonschema.validate(row, ASSET_SCHEMA)


def test_asset_ordering_is_deterministic():
    """API page order must not leak into the output, or reruns are not byte-identical."""
    feats = _feats()
    assert build_assets(list(reversed(feats)), _locs()) == build_assets(feats, _locs())


def test_assets_are_accepted_not_queued_for_review():
    """federation_export puts every needs_review ASSET into outputs/review_queue.json;
    80+ unactionable wells would drown the operator queue. Freshness lives in source_ref."""
    for row in build_assets(_feats(), _locs()):
        assert row["review_status"] == "accepted"
        assert "discrete measurement(s)" in row["source_ref"]


def test_absent_aquifer_assignment_is_stated_not_omitted():
    """The letter behind docs/LAGUNA_CARTAGENA_GAP.md asked for the well's aquifer.
    USGS publishes the field and leaves it null, which is an answer — so say so."""
    by_id = {a["asset_id"]: a for a in build_assets(_feats(), _locs())}
    assert "aquifer not assigned" in by_id[f"USGSFM_{WELL}"]["source_ref"]
    assert "aquifer not assigned" in by_id[f"USGSFM_{CEMETERY_WELL}"]["source_ref"]
    # ...and a well that HAS one records the code.
    assert "aquifer 110SCPL" in by_id["USGSFM_175711066143600"]["source_ref"]


def test_well_depth_and_altitude_ride_in_source_ref():
    """Both schemas are additionalProperties:false and have no field for them, and
    federation_export validates every row on export — an extra key fails the G01 gate."""
    row = next(a for a in build_assets(_feats(), _locs())
               if a["asset_id"] == "USGSFM_175711066143600")
    assert "land surface 4.9 ft" in row["source_ref"]
    assert "well depth" in row["source_ref"]
    assert not {"altitude", "well_depth", "aquifer_code"} & set(row)


def test_coordinates_outside_pr_bounds_are_dropped_not_clamped():
    feat = _synthetic()
    feat["geometry"]["coordinates"] = [-100.0, 45.0]
    row = build_assets([feat], {})[0]
    assert row["geometry_type"] == "unknown"
    assert "lat" not in row and "lon" not in row
    jsonschema.validate(row, ASSET_SCHEMA)


# ── readings ──────────────────────────────────────────────────────────────────
def test_build_readings_matches_schema_and_id_pattern():
    readings, _ = build_readings(_feats())
    assert readings
    pattern = READING_SCHEMA["properties"]["reading_id"]["pattern"]
    for row in readings:
        jsonschema.validate(row, READING_SCHEMA)
        assert re.match(pattern, row["reading_id"]), row["reading_id"]


def test_the_1985_well_measurements_are_recovered():
    """The gap docs/LAGUNA_CARTAGENA_GAP.md called unretrievable. Both codes, one visit."""
    readings, _ = build_readings(_feats())
    well = sorted((r for r in readings if r["site_no"] == WELL),
                  key=lambda r: r["parameter_code"])
    assert [(r["parameter_code"], r["value"], r["unit"], r["observed_date"]) for r in well] == [
        ("62610", 31.5, "ft", "1985-08-19"),
        ("72019", 11.2, "ft", "1985-08-19"),
    ]


def test_string_value_is_parsed_and_blank_value_is_skipped_not_zeroed():
    readings, skipped = build_readings([_synthetic(value=""), _synthetic(value="n/a")])
    assert readings == []
    assert skipped["no_value"] == 2


def test_negative_depth_is_kept():
    """A negative 72019 is a flowing artesian well, not bad data. No sign filter."""
    readings, _ = build_readings([_synthetic(value="-3.20")])
    assert readings[0]["value"] == pytest.approx(-3.2)


def test_date_comes_from_year_month_day_not_the_utc_timestamp():
    """When time_of_day is null the API fills `time` with a fabricated 12:00 UTC
    placeholder; slicing it can shift a UTC-4 measurement onto the wrong day."""
    feat = _synthetic(time="2026-01-03T00:30:00+00:00", time_of_day=None,
                      year=2026, month=1, day=2)
    readings, _ = build_readings([feat])
    assert readings[0]["observed_date"] == "2026-01-02"


def test_date_only_timestamp_still_resolves():
    feat = _synthetic(time="2026-01-02", time_of_day=None)
    del feat["properties"]["year"], feat["properties"]["month"], feat["properties"]["day"]
    readings, _ = build_readings([feat])
    assert readings[0]["observed_date"] == "2026-01-02"


def test_undated_measurement_is_skipped():
    feat = _synthetic(time="", time_of_day=None)
    del feat["properties"]["year"], feat["properties"]["month"], feat["properties"]["day"]
    readings, skipped = build_readings([feat])
    assert readings == [] and skipped["no_date"] == 1


def test_unitless_measurement_is_skipped():
    """monitoring_reading.unit requires a non-empty string."""
    readings, skipped = build_readings([_synthetic(unit_of_measure="")])
    assert readings == [] and skipped["no_unit"] == 1


def test_same_site_day_and_parameter_stay_distinct_by_reading_type():
    """(site, date, parameter_code) is NOT unique — a well can be visited twice a day."""
    readings, _ = build_readings([
        _synthetic(reading_type="ReferencePrimary"),
        _synthetic(reading_type="Routine", time_of_day="18:00:00+00:00"),
    ])
    assert len({r["reading_id"] for r in readings}) == 2


def test_reading_id_is_stable_when_only_the_value_changes():
    """The digest excludes `value`, so a USGS revision REPLACES the row on merge."""
    first, _ = build_readings([_synthetic(value="10.00")])
    later, _ = build_readings([_synthetic(value="10.50")])
    assert first[0]["reading_id"] == later[0]["reading_id"]
    assert first[0]["source_hash"] != later[0]["source_hash"]
    merged = merge_readings(first, later)
    assert len(merged) == 1 and merged[0]["value"] == pytest.approx(10.5)


def test_identical_upstream_duplicates_are_collapsed_and_counted():
    """Real capture: one series id published under two field_visit_ids. Collapsing is
    right, but silence is not — the run reports it."""
    readings, skipped = build_readings([_synthetic(), _synthetic()])
    assert len(readings) == 1 and skipped["duplicate"] == 1


def test_unapproved_measurement_is_flagged_provisional():
    approved, _ = build_readings([_synthetic(approval_status="Approved")])
    prov, _ = build_readings([_synthetic(approval_status="Provisional")])
    assert approved[0]["provisional"] is False
    assert prov[0]["provisional"] is True
    assert prov[0]["confidence"] < approved[0]["confidence"]


def test_static_qualifier_is_clean_and_anything_else_is_flagged():
    """Static is the condition you WANT. Every one of 648 live PR readings carries it, so
    flagging it would mark the whole corpus for review and mean nothing. Pumping is a
    drawdown at the pump, not a static water table."""
    static, _ = build_readings([_synthetic(qualifier=["Static"])])
    none_, _ = build_readings([_synthetic(qualifier=None)])
    pumping, _ = build_readings([_synthetic(qualifier=["Above", "Pumping"])])
    assert static[0]["review_status"] == "accepted"
    assert none_[0]["review_status"] == "accepted"
    assert pumping[0]["review_status"] == "needs_review"
    assert "Pumping" in pumping[0]["source_ref"]


def test_string_qualifier_is_tolerated():
    """The API publishes a list, but a bare string must not explode into characters."""
    readings, _ = build_readings([_synthetic(qualifier="Pumping")])
    assert readings[0]["review_status"] == "needs_review"
    assert "qualifiers Pumping" in readings[0]["source_ref"]


def test_both_parameter_codes_map_to_the_same_closed_enum_metric():
    readings, _ = build_readings(_feats())
    allowed = set(READING_SCHEMA["properties"]["metric"]["enum"])
    assert {r["metric"] for r in readings} == {GW_METRIC} <= allowed
    assert {"72019", "62610"} <= {r["parameter_code"] for r in readings}


def test_datum_is_recorded_in_source_ref_because_the_schema_has_no_field_for_it():
    readings, _ = build_readings([_synthetic(vertical_datum="NGVD29")])
    assert "datum=NGVD29" in readings[0]["source_ref"]
    assert "datum" not in readings[0]


def test_default_parameter_codes_exclude_62610():
    """62610 (elevation ABOVE datum) runs opposite to 72019 (depth BELOW surface), and
    water_alerts drives _AQUIFER_METRICS with direction='high'. Mixing them inverts the
    drawdown signal, so 62610 stays opt-in."""
    assert DEFAULT_PARAMETER_CODES == ("72019",)


def test_this_vector_is_not_wired_into_the_alert_proxy():
    """build_alerts.py names its three reading files explicitly and does not glob.
    That is what keeps 62610 out of the aquifer proxy — guard it against a casual edit."""
    src = (REPO / "scripts" / "build_alerts.py").read_text()
    assert "_readings.jsonl" not in src
    assert "usgs_field_measurements" not in src


# ── merge semantics ───────────────────────────────────────────────────────────
def test_merge_assets_preserves_the_daily_groundwater_wells():
    existing = [{"asset_id": "USGSGW_500001"}, {"asset_id": "USGS_50129899"},
                {"asset_id": f"USGSFM_{WELL}", "asset_name": "stale"}]
    merged = merge_assets(existing, build_assets(_feats(), _locs()))
    by_id = {r["asset_id"]: r for r in merged}
    assert {"USGSGW_500001", "USGS_50129899"} <= set(by_id)
    assert by_id[f"USGSFM_{WELL}"]["asset_name"] != "stale"


def test_merge_assets_never_deletes_a_well_outside_the_current_window():
    """Readings are permanent, so their assets must be. A prefix-wide replace would
    orphan every reading for a well that fell outside a narrowed --days window."""
    existing = [{"asset_id": "USGSFM_999999", "asset_name": "measured long ago"}]
    merged = merge_assets(existing, build_assets(_feats(), _locs()))
    assert "USGSFM_999999" in {r["asset_id"] for r in merged}


def test_merges_are_idempotent():
    assets = build_assets(_feats(), _locs())
    readings, _ = build_readings(_feats())
    assert merge_assets(merge_assets([], assets), assets) == merge_assets([], assets)
    assert merge_readings(merge_readings([], readings), readings) == merge_readings([], readings)


# ── parsing / pagination ──────────────────────────────────────────────────────
def test_parse_features_flattens_multiple_pages_without_loss_or_dedup():
    page = _doc()
    assert len(parse_features([page, page])) == 2 * len(parse_features(page))


def test_parse_locations_keys_on_the_bare_site_number():
    locs = _locs()
    assert WELL in locs
    assert locs[WELL]["site_type_code"] == "GW"
    assert locs[WELL]["aquifer_code"] is None      # published, and empty


def test_year_slicing_covers_the_range_without_gaps_or_overlaps():
    """Required, not an optimization: a whole-bbox decade query is cancelled server-side
    with InvalidQuery 'Long running query has been cancelled.'"""
    slices = _year_slices("2024-03-01", "2026-02-01")
    assert slices == [("2024-03-01", "2025-01-01"),
                      ("2025-01-01", "2026-01-01"),
                      ("2026-01-01", "2026-02-01")]
    assert all(a < b for a, b in slices)


def test_bbox_default_matches_the_repo_pr_bounds():
    """Reused from ingest_usgs_water, not hand-typed — the same bounds the asset schema
    enforces, so the fetch window and the accept window cannot drift apart."""
    from ingest_usgs_water import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN

    assert f"{LON_MIN},{LAT_MIN},{LON_MAX},{LAT_MAX}" == DEFAULT_BBOX


# ── CLI ───────────────────────────────────────────────────────────────────────
def test_offline_run_writes_valid_output(tmp_path):
    out = tmp_path / "readings.jsonl"
    assets = tmp_path / "assets.jsonl"
    cmd = [
        sys.executable, str(REPO / "scripts" / "ingest_usgs_field_measurements.py"),
        "--src", str(FIXTURES / "usgs_field_measurements_pr.json"),
        "--src-locations", str(FIXTURES / "usgs_monitoring_locations_pr.json"),
        "--assets-out", str(assets), "--readings-out", str(out),
    ]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    assert rows
    for row in rows:
        jsonschema.validate(row, READING_SCHEMA)
    for row in [json.loads(ln) for ln in assets.read_text().splitlines() if ln.strip()]:
        jsonschema.validate(row, ASSET_SCHEMA)

    # A second run over the same input must be byte-identical.
    before = out.read_bytes(), assets.read_bytes()
    assert subprocess.run(cmd, cwd=REPO, capture_output=True, text=True).returncode == 0
    assert (out.read_bytes(), assets.read_bytes()) == before
