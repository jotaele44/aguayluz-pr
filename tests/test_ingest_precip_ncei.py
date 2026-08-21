"""Tests for the NCEI precipitation ingester (scripts/ingest_precip_ncei.py). No network."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_precip_ncei import (  # noqa: E402
    PR_STATIONS,
    build_asset,
    build_readings,
    parse_daily,
    parse_normals,
    window_normal_mm,
    window_observed_mm,
)

ROOT = Path(__file__).resolve().parents[1]
READING_SCHEMA = json.loads((ROOT / "schemas" / "monitoring_reading.schema.json").read_text())
ASSET_SCHEMA = json.loads((ROOT / "schemas" / "utility_asset.schema.json").read_text())


# ── asset ────────────────────────────────────────────────────────────────────
def test_build_asset_matches_schema():
    station = PR_STATIONS[0]
    asset = build_asset(station)
    assert asset["asset_id"] == f"NCEI_{station['id']}"
    assert asset["asset_type"] == "water" and asset["asset_subtype"] == "precipitation_gauge"
    assert asset["lat"] == station["lat"]
    jsonschema.validate(asset, ASSET_SCHEMA)


# ── parsing: both datasets requested with units=metric, so both are already mm ──
def test_parse_normals_reads_metric_mm_values():
    raw = json.dumps([
        {"DATE": "01", "STATION": "S1", "MLY-PRCP-NORMAL": "95.50"},
        {"DATE": "02", "STATION": "S1", "MLY-PRCP-NORMAL": "60.71"},
    ])
    normals = parse_normals(raw)
    assert normals["S1"][1] == pytest.approx(95.50)
    assert normals["S1"][2] == pytest.approx(60.71)


def test_parse_daily_skips_missing_prcp_rather_than_zero_filling():
    raw = json.dumps([
        {"DATE": "2024-06-01", "STATION": "S1", "PRCP": "0.0"},
        {"DATE": "2024-06-02", "STATION": "S1"},  # no PRCP key: a real gap, not a dry day
        {"DATE": "2024-06-03", "STATION": "S1", "PRCP": "29.2"},
    ])
    daily = parse_daily(raw)
    assert daily["S1"] == {"2024-06-01": 0.0, "2024-06-03": 29.2}


# ── calendar-weighted normal ─────────────────────────────────────────────────
def test_window_normal_mm_prorates_across_a_month_boundary():
    # Jan normal 310mm = 10mm/day * 31; Feb normal 280mm = 10mm/day * 28.
    normals = {1: 310.0, 2: 280.0}
    # 5-day window Jan 30 - Feb 3: 2 Jan days + 3 Feb days, both at 10mm/day -> 50mm.
    assert window_normal_mm(normals, date(2024, 2, 3), 5) == pytest.approx(50.0)


def test_window_normal_mm_none_when_a_month_is_missing():
    assert window_normal_mm({1: 310.0}, date(2024, 2, 3), 5) is None


# ── observed accumulation + coverage ─────────────────────────────────────────
def test_window_observed_mm_reports_partial_coverage():
    daily = {f"2024-01-{d:02d}": 10.0 for d in range(1, 22)}  # 21 of 30 days
    total, coverage = window_observed_mm(daily, date(2024, 1, 30), 30)
    assert total == pytest.approx(210.0)
    assert coverage == pytest.approx(21 / 30)


# ── build_readings: end-to-end percent-of-normal ─────────────────────────────
def test_build_readings_computes_percent_of_normal_with_full_coverage():
    daily = {f"2024-01-{d:02d}": 10.0 for d in range(1, 31)}  # 30 days observed
    normals = {1: 300.0}
    fetch_start, fetch_end = date(2024, 1, 1), date(2024, 1, 30)
    rows = build_readings("S1", daily, normals, fetch_start, fetch_end)
    # Only day 30 has a full 30-day lookback within the fetch window; no 90d window fits.
    assert len(rows) == 1
    r = rows[0]
    assert r["metric"] == "precipitation_pct_normal"
    assert r["parameter_code"] == "30d"
    assert r["site_no"] == "S1" and r["asset_id"] == "NCEI_S1"
    assert r["observed_date"] == "2024-01-30"
    expected_normal = window_normal_mm(normals, date(2024, 1, 30), 30)
    assert r["value"] == pytest.approx(round(100.0 * 300.0 / expected_normal, 1))
    jsonschema.validate(r, READING_SCHEMA)


def test_build_readings_skips_window_below_minimum_coverage():
    # Only 15 of 30 days present (50% < the 70% MIN_COVERAGE floor) -> a real gap,
    # not zero-filled or extrapolated into a reading.
    daily = {f"2024-01-{d:02d}": 10.0 for d in range(1, 16)}
    normals = {1: 300.0}
    rows = build_readings("S1", daily, normals, date(2024, 1, 1), date(2024, 1, 30))
    assert rows == []
