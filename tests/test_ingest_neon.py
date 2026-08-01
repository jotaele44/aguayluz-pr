"""scripts/ingest_neon.py — assets, availability registry, and the publication delta.

Every built asset row is validated against the real schemas/utility_asset.schema.json,
matching the convention in tests/test_ingest_noaa_tides.py. No network.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ingest_neon import (  # noqa: E402
    build_asset,
    build_availability,
    diff_availability,
    merge_assets,
    merge_availability,
    merge_events,
)

FIXTURES = REPO / "tests" / "fixtures"
ASSET_SCHEMA = json.loads((REPO / "schemas" / "utility_asset.schema.json").read_text())


@pytest.fixture
def cupe_doc() -> dict:
    return json.loads((FIXTURES / "neon_site_cupe_sample.json").read_text())["data"]


# ── assets ────────────────────────────────────────────────────────────────────
def test_build_asset_matches_schema(cupe_doc):
    row = build_asset(cupe_doc)
    jsonschema.validate(row, ASSET_SCHEMA)
    assert row["asset_id"] == "NEON_CUPE"
    assert row["asset_type"] == "water"
    assert row["asset_subtype"] == "research_station_aquatic"
    assert row["operator"] == "NSF NEON"
    assert row["evidence_tier"] == "T1"
    assert row["geometry_type"] == "point"
    assert row["lat"] == pytest.approx(18.11352)
    assert row["lon"] == pytest.approx(-66.98676)


def test_terrestrial_site_keeps_its_habitat_in_the_subtype():
    """asset_type must collapse to `water`; the habitat distinction must not be lost."""
    doc = {
        "siteCode": "GUAN", "siteName": "Guánica Forest NEON", "siteType": "CORE",
        "siteLatitude": 17.96955, "siteLongitude": -66.86870, "dataProducts": [],
    }
    row = build_asset(doc)
    jsonschema.validate(row, ASSET_SCHEMA)
    assert row["asset_type"] == "water"
    assert row["asset_subtype"] == "research_station_terrestrial"


def test_build_asset_is_deterministic(cupe_doc):
    assert build_asset(cupe_doc) == build_asset(cupe_doc)


def test_merge_assets_preserves_other_providers(cupe_doc):
    existing = [
        {"asset_id": "USGS_50059000"},
        {"asset_id": "NOAA_9755371"},
        {"asset_id": "NEON_CUPE", "asset_name": "stale"},
    ]
    merged = merge_assets(existing, [build_asset(cupe_doc)])
    by_id = {r["asset_id"]: r for r in merged}
    assert set(by_id) == {"USGS_50059000", "NOAA_9755371", "NEON_CUPE"}
    assert by_id["NEON_CUPE"]["asset_name"] != "stale"


# ── availability registry ─────────────────────────────────────────────────────
def test_build_availability_one_row_per_product(cupe_doc):
    rows = build_availability(cupe_doc)
    assert len(rows) == len(cupe_doc["dataProducts"])
    row = next(r for r in rows if r["product_code"] == "DP4.00130.001")
    assert row["registry_id"] == "NEON_CUPE_DP4.00130.001"
    assert row["neon_site"] == "CUPE"
    assert row["habitat"] == "aquatic"
    assert row["ingestible"] is True          # maps onto the closed metric enum
    assert row["month_count"] > 0
    assert row["latest_month"] >= row["first_month"]
    assert len(row["months_sha256"]) == 64


def test_deferred_product_is_tracked_but_not_ingestible(cupe_doc):
    """Precipitation has no `metric` enum value yet — tracked, not promoted."""
    rows = {r["product_code"]: r for r in build_availability(cupe_doc)}
    assert rows["DP1.00045.001"]["ingestible"] is False


def test_availability_hash_changes_with_the_month_list(cupe_doc):
    before = {r["product_code"]: r for r in build_availability(cupe_doc)}
    doc = json.loads(json.dumps(cupe_doc))
    doc["dataProducts"][0]["availableMonths"].append("2026-07")
    after = {r["product_code"]: r for r in build_availability(doc)}
    code = doc["dataProducts"][0]["dataProductCode"]
    assert before[code]["months_sha256"] != after[code]["months_sha256"]


# ── delta ─────────────────────────────────────────────────────────────────────
TODAY = date(2026, 7, 29)


def _rows(cupe_doc):
    return build_availability(cupe_doc)


def test_bootstrap_run_emits_no_changes(cupe_doc):
    """No previous state means no delta — never ~328 spurious `new_product` alerts."""
    assert diff_availability([], _rows(cupe_doc), today=TODAY) == []


def test_new_month_detected(cupe_doc):
    current = _rows(cupe_doc)
    previous = json.loads(json.dumps(current))
    target = next(r for r in previous if r["product_code"] == "DP4.00130.001")
    target["latest_month"] = "2020-01"
    target["months_sha256"] = "stale"

    changes = diff_availability(previous, current, today=TODAY)
    rec = next(c for c in changes if c["change_type"] == "new_month")
    assert rec["product_code"] == "DP4.00130.001"
    assert rec["previous_latest_month"] == "2020-01"
    assert rec["event_id"] == f"CUPE_DP4.00130.001_new_month_{rec['latest_month']}"


def test_backfilled_month_detected(cupe_doc):
    """latest_month unchanged but the hash moved: a historical month was corrected."""
    current = _rows(cupe_doc)
    previous = json.loads(json.dumps(current))
    next(r for r in previous if r["product_code"] == "DP1.20093.001")["months_sha256"] = "different"

    changes = diff_availability(previous, current, today=TODAY)
    types = {c["product_code"]: c["change_type"] for c in changes}
    assert types["DP1.20093.001"] == "backfilled_month"


def test_new_product_detected(cupe_doc):
    current = _rows(cupe_doc)
    previous = [r for r in json.loads(json.dumps(current)) if r["product_code"] != "DP1.20016.001"]
    changes = diff_availability(previous, current, today=TODAY)
    rec = next(c for c in changes if c["change_type"] == "new_product")
    assert rec["product_code"] == "DP1.20016.001"
    assert rec["previous_latest_month"] is None


def test_new_release_detected(cupe_doc):
    current = _rows(cupe_doc)
    previous = json.loads(json.dumps(current))
    for r in previous:
        r["latest_release"] = "RELEASE-2020"
    changes = diff_availability(previous, current, today=TODAY)
    releases = [c for c in changes if c["change_type"] == "new_release"]
    assert releases and releases[0]["previous_release"] == "RELEASE-2020"


def test_publication_gap_only_for_monthly_cadence_products(cupe_doc):
    """A campaign-sampled product must not be flagged stale for being irregular."""
    current = _rows(cupe_doc)
    for r in current:
        r["latest_month"] = "2025-01"          # ~18 months behind TODAY
    previous = json.loads(json.dumps(current))
    changes = diff_availability(previous, current, today=TODAY, stale_months=3)
    gapped = {c["product_code"] for c in changes if c["change_type"] == "publication_gap"}
    assert "DP4.00130.001" in gapped          # continuous sensor -> real signal
    assert "DP1.20193.001" not in gapped      # salt-based campaign -> irregular by design
    assert "DP1.00001.001" not in gapped      # not an ingestible product at all


def test_steady_state_yields_no_changes(cupe_doc):
    current = _rows(cupe_doc)
    previous = json.loads(json.dumps(current))
    assert diff_availability(previous, current, today=date(2026, 7, 1)) == []


# ── merge semantics ───────────────────────────────────────────────────────────
def test_merge_availability_carries_first_seen_and_only_stamps_real_change(cupe_doc):
    current = _rows(cupe_doc)
    first = merge_availability([], current, "2026-01-01T00:00:00Z")
    assert all(r["first_seen"] == "2026-01-01T00:00:00Z" for r in first)

    # unchanged re-run must not churn last_changed (or every refresh dirties 328 rows)
    second = merge_availability(first, current, "2026-02-01T00:00:00Z")
    assert all(r["first_seen"] == "2026-01-01T00:00:00Z" for r in second)
    assert all(r["last_changed"] == "2026-01-01T00:00:00Z" for r in second)

    moved = json.loads(json.dumps(current))
    moved[0]["months_sha256"] = "changed"
    third = merge_availability(second, moved, "2026-03-01T00:00:00Z")
    changed = next(r for r in third if r["registry_id"] == moved[0]["registry_id"])
    assert changed["last_changed"] == "2026-03-01T00:00:00Z"
    assert changed["first_seen"] == "2026-01-01T00:00:00Z"


def test_merge_availability_is_idempotent(cupe_doc):
    current = _rows(cupe_doc)
    once = merge_availability([], current, "2026-01-01T00:00:00Z")
    twice = merge_availability(once, current, "2026-01-01T00:00:00Z")
    assert once == twice


def test_merge_events_dedupes_and_keeps_first_detection():
    existing = [{"event_id": "A", "detected_at": "2026-01-01T00:00:00Z"}]
    new = [
        {"event_id": "A", "detected_at": "2026-02-01T00:00:00Z"},  # re-detection
        {"event_id": "B", "detected_at": "2026-02-01T00:00:00Z"},
    ]
    merged = merge_events(existing, new, keep=10)
    by_id = {r["event_id"]: r for r in merged}
    assert set(by_id) == {"A", "B"}
    # first detection wins, so the alert derived from it keeps a stable timestamp
    assert by_id["A"]["detected_at"] == "2026-01-01T00:00:00Z"


def test_merge_events_retains_newest_within_cap():
    existing = [{"event_id": str(i), "detected_at": f"2026-01-{i:02d}T00:00:00Z"} for i in range(1, 11)]
    merged = merge_events(existing, [], keep=3)
    assert [r["event_id"] for r in merged] == ["8", "9", "10"]
