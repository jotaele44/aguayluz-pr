"""scripts/ingest_neon_products.py — the token-gated download + CSV parse half.

Every reading row is validated against the real schemas/monitoring_reading.schema.json.

Fixture caveat, repeated here because it matters when reading a failure: the NEON
file-manifest endpoint is credential-gated (HTTP 403 anonymously) and no token was
available when these tests were written, so neon_data_manifest_sample.json and
neon_continuous_discharge_sample.csv are SYNTHETIC — hand-authored from NEON's
published response and file formats, not recorded from a live call. They exercise
this repo's parsing and integrity logic correctly; they do NOT prove the column
names match a real NEON download.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ingest_neon_products import (  # noqa: E402
    CSV_COLUMNS,
    build_readings,
    merge_readings,
    select_files,
    select_targets,
)

FIXTURES = REPO / "tests" / "fixtures"
READING_SCHEMA = json.loads((REPO / "schemas" / "monitoring_reading.schema.json").read_text())
CSV_TEXT = (FIXTURES / "neon_continuous_discharge_sample.csv").read_text()
MANIFEST = json.loads((FIXTURES / "neon_data_manifest_sample.json").read_text())["data"]


# ── CSV -> readings ───────────────────────────────────────────────────────────
def test_build_readings_matches_schema():
    rows = build_readings(CSV_TEXT, "DP4.00130.001", "CUPE", provisional=True, release="PROVISIONAL")
    assert rows
    for row in rows:
        jsonschema.validate(row, READING_SCHEMA)


def test_reading_ids_are_daily_and_pattern_valid():
    rows = build_readings(CSV_TEXT, "DP4.00130.001", "CUPE")
    ids = [r["reading_id"] for r in rows]
    assert ids == sorted(set(ids))                       # one row per day, deduped
    pattern = READING_SCHEMA["properties"]["reading_id"]["pattern"]
    import re
    assert all(re.match(pattern, i) for i in ids)
    assert ids[0] == "AYL_RDG_20260601_NEON_CUPE_streamflow"


def test_qa_flagged_rows_are_dropped():
    """finalQF=1 is a failed sensor check — it must not reach the reading store."""
    rows = {r["observed_date"]: r for r in build_readings(CSV_TEXT, "DP4.00130.001", "CUPE")}
    # 2026-06-01 has three good half-hours (1250/1310/1290 L/s) plus one flagged 99999.
    assert rows["2026-06-01"]["value"] == pytest.approx((1250 + 1310 + 1290) / 3 / 1000)


def test_units_are_converted_not_relabelled():
    """NEON publishes discharge in L/s; the schema row must carry m3/s values."""
    rows = {r["observed_date"]: r for r in build_readings(CSV_TEXT, "DP4.00130.001", "CUPE")}
    assert rows["2026-06-02"]["unit"] == "m3/s"
    assert rows["2026-06-02"]["value"] == pytest.approx((980 + 1020) / 2 / 1000)


# ── unit/column binding — the "matched the wrong column" class of bug ──────────
def test_every_value_candidate_for_a_product_shares_one_unit():
    """Structural guard against reintroducing a mislabelling fallback.

    Falling back to a column that measures a DIFFERENT quantity would emit a
    plausible-looking wrong number (a temperature labelled as conductance) instead
    of failing. Candidates must be naming variants of one measurement, so they must
    agree on the unit; a genuinely different analyte gets its own product entry.
    """
    for product_code, spec in CSV_COLUMNS.items():
        units = {c["unit"] for c in spec["value"]}
        assert len(units) == 1, f"{product_code}: candidates disagree on unit: {units}"


def test_every_value_candidate_carries_its_own_unit_and_scale():
    """Unit and scale must bind to the column, never to the product."""
    for product_code, spec in CSV_COLUMNS.items():
        assert "unit" not in spec and "scale" not in spec, (
            f"{product_code}: unit/scale at product level lets a fallback inherit the wrong one"
        )
        for cand in spec["value"]:
            assert set(cand) == {"column", "unit", "scale"}, f"{product_code}: {cand}"


def test_fallback_column_uses_its_own_unit_not_the_first_candidates():
    """The regression this fix exists for.

    A file carrying only the SECOND candidate must be read with that candidate's
    unit and scale. Previously unit/scale lived on the product, so the fallback
    silently inherited the first candidate's.
    """
    csv_text = (
        "siteID,endDate,surfacewaterElev,finalQF\n"
        "CUPE,2026-06-01T00:00:00Z,3.5,0\n"
    )
    rows = build_readings(csv_text, "DP1.20016.001", "CUPE")
    assert len(rows) == 1
    second = next(c for c in CSV_COLUMNS["DP1.20016.001"]["value"] if c["column"] == "surfacewaterElev")
    assert rows[0]["unit"] == second["unit"]
    assert rows[0]["value"] == pytest.approx(3.5 * second["scale"])


def test_different_quantity_is_skipped_not_mislabelled():
    """`waterTemp` is no longer a fallback for surface-water chemistry.

    A file with only waterTemp must yield nothing — not a temperature stored under
    `water_quality` with a conductance unit.
    """
    csv_text = "siteID,collectDate,waterTemp,finalQF\nCUPE,2026-06-01T00:00:00Z,24.8,0\n"
    assert build_readings(csv_text, "DP1.20093.001", "CUPE") == []


def test_different_analyte_is_skipped_not_mislabelled():
    """Same rule for dissolved gases: CH4 is not a naming variant of CO2."""
    csv_text = "siteID,collectDate,dissolvedCH4,finalQF\nCUPE,2026-06-01T00:00:00Z,0.0004,0\n"
    assert build_readings(csv_text, "DP1.20097.001", "CUPE") == []


def test_product_metrics_does_not_carry_a_unit():
    """Single source of truth: unit lives on the column, not the product."""
    from aguayluz.neon.mapping import PRODUCT_METRICS as PM
    for code, meta in PM.items():
        assert "unit" not in meta, f"{code}: a product-level unit is a second source of truth"


def test_blank_values_skipped_not_zeroed():
    rows = {r["observed_date"]: r for r in build_readings(CSV_TEXT, "DP4.00130.001", "CUPE")}
    assert rows["2026-06-03"]["value"] == pytest.approx(2400 / 1000)


def test_metric_and_parameter_code_carry_provenance():
    row = build_readings(CSV_TEXT, "DP4.00130.001", "CUPE", release="RELEASE-2026")[0]
    assert row["metric"] == "streamflow"
    assert row["parameter_code"] == "DP4.00130.001"
    assert row["asset_id"] == "NEON_CUPE"
    assert row["site_no"] == "CUPE"
    assert row["evidence_tier"] == "T1"
    assert "RELEASE-2026" in row["source_ref"]


def test_provisional_lowers_confidence():
    final = build_readings(CSV_TEXT, "DP4.00130.001", "CUPE", provisional=False)[0]
    prov = build_readings(CSV_TEXT, "DP4.00130.001", "CUPE", provisional=True)[0]
    assert prov["confidence"] < final["confidence"]
    assert prov["provisional"] is True


def test_unknown_columns_skip_the_file_rather_than_guess(capsys):
    """Fail safe: a file with no documented column yields nothing, never a wrong column."""
    rows = build_readings("siteID,someOtherColumn\nCUPE,42\n", "DP4.00130.001", "CUPE")
    assert rows == []
    assert "no known date/value column" in capsys.readouterr().err


def test_groundwater_chemistry_is_mapped_and_single_candidate():
    """DP1.20092.001 reads specificConductance only — no guessed fallback, per the
    rule that a wrong column which happens to exist is worse than no reading."""
    spec = CSV_COLUMNS["DP1.20092.001"]
    assert [c["column"] for c in spec["value"]] == ["specificConductance"]
    assert spec["value"][0]["unit"] == "uS/cm"
    csv_text = (
        "siteID,collectDate,specificConductance,finalQF\n"
        "GUIL,2026-05-01T00:00:00Z,412.5,0\n"
    )
    rows = build_readings(csv_text, "DP1.20092.001", "GUIL")
    assert len(rows) == 1
    jsonschema.validate(rows[0], READING_SCHEMA)
    assert rows[0]["metric"] == "water_quality"
    assert rows[0]["unit"] == "uS/cm"
    assert rows[0]["asset_id"] == "NEON_GUIL"


def test_unmapped_product_yields_nothing():
    """Precipitation has no metric enum value — it must not be silently stored."""
    assert build_readings(CSV_TEXT, "DP1.00045.001", "CUPE") == []


# ── manifest handling ─────────────────────────────────────────────────────────
def test_select_files_keeps_only_basic_data_csvs():
    names = [f["name"] for f in select_files(MANIFEST)]
    assert all(n.endswith(".csv") for n in names)
    assert not any("readme" in n.lower() or "variables" in n.lower() for n in names)
    assert len(names) == 2  # the good CSV and the deliberately-corrupt one


def test_manifest_md5_matches_the_real_fixture_bytes():
    """The integrity check is only meaningful if the fixture digest is genuine."""
    import hashlib
    good = next(f for f in MANIFEST["files"] if "Corrupt" not in f["name"] and "basic" in f["name"])
    expected = hashlib.md5((FIXTURES / "neon_continuous_discharge_sample.csv").read_bytes()).hexdigest()  # noqa: S324
    assert good["md5"] == expected


# ── target selection ──────────────────────────────────────────────────────────
TODAY = date(2026, 7, 29)


def test_new_month_fetches_only_that_month():
    targets = select_targets(
        [{"change_type": "new_month", "product_code": "DP4.00130.001",
          "neon_site": "CUPE", "latest_month": "2026-06"}],
        today=TODAY,
    )
    assert [(t["neon_site"], t["month"]) for t in targets] == [("CUPE", "2026-06")]


def test_non_ingestible_product_is_never_downloaded():
    targets = select_targets(
        [{"change_type": "new_month", "product_code": "DP1.00045.001",
          "neon_site": "LAJA", "latest_month": "2026-06"}],
        today=TODAY,
    )
    assert targets == []


def test_publication_gap_downloads_nothing():
    """A gap is an alert, not a fetch — there is nothing new to download."""
    targets = select_targets(
        [{"change_type": "publication_gap", "product_code": "DP4.00130.001",
          "neon_site": "CUPE", "latest_month": "2026-02"}],
        today=TODAY,
    )
    assert targets == []


def test_backfill_pulls_a_bounded_window():
    targets = select_targets(
        [{"change_type": "backfilled_month", "product_code": "DP4.00130.001",
          "neon_site": "CUPE", "latest_month": "2026-06"}],
        months_back=2, today=TODAY,
    )
    months = {t["month"] for t in targets}
    assert months <= {"2026-07", "2026-06", "2026-05"}
    assert "2026-06" in months
    assert all(m <= "2026-06" for m in months)   # never asks for unpublished months


def test_targets_are_deduped():
    changes = [
        {"change_type": "new_month", "product_code": "DP4.00130.001",
         "neon_site": "CUPE", "latest_month": "2026-06"},
        {"change_type": "new_month", "product_code": "DP4.00130.001",
         "neon_site": "CUPE", "latest_month": "2026-06"},
    ]
    assert len(select_targets(changes, today=TODAY)) == 1


# ── merge ─────────────────────────────────────────────────────────────────────
def test_merge_readings_is_idempotent():
    rows = build_readings(CSV_TEXT, "DP4.00130.001", "CUPE")
    once = merge_readings([], rows)
    assert merge_readings(once, rows) == once


# ── CLI contract ──────────────────────────────────────────────────────────────
def test_missing_token_exits_zero_and_says_why(tmp_path, monkeypatch):
    """A token-less refresh must warn and continue, not fail the whole run."""
    env = {k: v for k, v in __import__("os").environ.items()
           if k not in ("NEON_API_TOKEN", "NEON_API_KEY")}
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ingest_neon_products.py"),
         "--readings-out", str(tmp_path / "out.jsonl")],
        cwd=REPO, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "NEON_API_TOKEN not set" in proc.stdout
    assert "403" in proc.stdout


def test_offline_csv_path_writes_valid_readings(tmp_path):
    out = tmp_path / "neon_readings.jsonl"
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ingest_neon_products.py"),
         "--src-manifest", str(FIXTURES / "neon_data_manifest_sample.json"),
         "--src-csv", str(FIXTURES / "neon_continuous_discharge_sample.csv"),
         "--product", "DP4.00130.001", "--site", "CUPE",
         "--readings-out", str(out)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    assert rows
    for row in rows:
        jsonschema.validate(row, READING_SCHEMA)
