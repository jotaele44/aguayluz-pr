import json
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aguayluz.models import validate_against_schema  # noqa: E402
from aguayluz.water_balance import build_balance_intervals  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INTERVAL_SCHEMA = json.loads((ROOT / "schemas" / "water_balance_interval.schema.json").read_text())
QUARANTINE_SCHEMA = json.loads((ROOT / "schemas" / "water_balance_quarantine.schema.json").read_text())
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def reading(reading_id, metric, value, unit, source_hash, *, parameter_code=None, confidence=90):
    return {
        "reading_id": reading_id,
        "asset_id": "AYL_SITE_ILOS",
        "site_no": "ILOS",
        "metric": metric,
        "parameter_code": parameter_code,
        "value": value,
        "unit": unit,
        "observed_date": "2026-08-05",
        "source_ref": f"operator ledger {reading_id}",
        "source_hash": source_hash,
        "evidence_tier": "T2",
        "confidence": confidence,
        "review_status": "accepted",
    }


def test_accepted_interval_requires_explicit_roles_and_hashes():
    rows = [
        reading("IN_1", "other", 10.0, "Mgal/day", HASH_A),
        reading("OUT_1", "other", 7.5, "Mgal/day", HASH_B),
        reading("STO_1", "other", 1.0, "Mgal", HASH_C),
    ]
    role_map = {"IN_1": "inflow", "OUT_1": "outflow", "STO_1": "storage"}
    intervals, quarantines = build_balance_intervals(
        rows, role_map, interval_start="2026-08-05", interval_end="2026-08-05"
    )
    assert quarantines == []
    assert len(intervals) == 1
    interval = intervals[0]
    assert interval["balance_status"] == "accepted"
    assert interval["inflow_volume"] == 10.0
    assert interval["outflow_volume"] == 7.5
    assert interval["storage_delta"] == 1.0
    assert interval["unaccounted_volume"] == 1.5
    validate_against_schema("water_balance_interval", interval)
    jsonschema.validate(interval, INTERVAL_SCHEMA)


def test_no_role_and_missing_hash_are_quarantined():
    rows = [reading("IN_1", "streamflow", 3.0, "ft3/s", None)]
    intervals, quarantines = build_balance_intervals(
        rows, {}, interval_start="2026-08-05", interval_end="2026-08-05"
    )
    assert intervals == []
    codes = {row["quarantine_code"] for row in quarantines}
    assert codes == {"NO_EXPLICIT_BALANCE_ROLE", "MISSING_SOURCE_HASH"}
    for row in quarantines:
        validate_against_schema("water_balance_quarantine", row)
        jsonschema.validate(row, QUARANTINE_SCHEMA)


def test_inflow_outflow_without_storage_is_degraded():
    rows = [
        reading("IN_1", "other", 2.0, "Mgal/day", HASH_A),
        reading("OUT_1", "other", 1.5, "Mgal/day", HASH_B),
    ]
    intervals, quarantines = build_balance_intervals(
        rows,
        {"IN_1": "inflow", "OUT_1": "outflow"},
        interval_start="2026-08-05",
        interval_end="2026-08-05",
    )
    assert quarantines == []
    assert intervals[0]["balance_status"] == "degraded"
    assert intervals[0]["quarantine_codes"] == ["MISSING_STORAGE_DELTA"]
    assert intervals[0]["review_status"] == "needs_review"


def test_units_that_need_rating_curve_block_input():
    rows = [reading("STO_1", "reservoir_elevation", 43.0, "ft", HASH_A)]
    intervals, quarantines = build_balance_intervals(
        rows,
        {"STO_1": "storage"},
        interval_start="2026-08-05",
        interval_end="2026-08-05",
    )
    assert intervals == []
    assert {row["quarantine_code"] for row in quarantines} == {"UNIT_NOT_BALANCE_VOLUME"}


def test_synthetic_input_rejected_in_production_mode():
    row = reading("IN_1", "other", 1.0, "Mgal/day", HASH_A)
    row["synthetic"] = True
    intervals, quarantines = build_balance_intervals(
        [row],
        {"IN_1": "inflow"},
        interval_start="2026-08-05",
        interval_end="2026-08-05",
        production_mode=True,
    )
    assert intervals == []
    assert {q["quarantine_code"] for q in quarantines} == {"SYNTHETIC_PRODUCTION_INPUT"}
