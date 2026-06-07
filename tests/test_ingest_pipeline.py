"""Tests for the generic ingest pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from aguayluz.ingest import FacilitySeed, ingest_seeds
from aguayluz.ingest.frs import parse_frs_response

FIXTURES = Path(__file__).parent / "fixtures"


def _waters_fixture() -> dict:
    return json.loads((FIXTURES / "waters" / "pointindexing_lago_la_plata.json").read_text())


def _ok_seed(seed_id: str, lat: float = 18.388, lon: float = -66.232) -> FacilitySeed:
    return FacilitySeed(
        seed_id=seed_id,
        name="Test asset",
        municipality="Toa Alta",
        asset_type="water",
        asset_subtype="intake",
        lat=lat,
        lon=lon,
        operator="PRASA",
        source_provenance="test",
    )


def test_single_seed_produces_one_asset():
    snap = _waters_fixture()
    result = ingest_seeds([_ok_seed("AYL_AST_X")], snap_fn=lambda _lo, _la: snap)
    assert len(result.assets) == 1
    assert result.assets[0]["asset_id"] == "AYL_AST_X"
    assert result.assets[0]["attribute_coverage"] == "partial"  # VPU 21
    assert result.review_items == []
    assert result.skipped == []
    assert result.coverage_pct == 100.0


def test_missing_coords_route_to_review():
    seed = FacilitySeed(
        seed_id="AYL_AST_NULL",
        name="No-coords facility",
        municipality="Bayamon",
        asset_type="water",
        asset_subtype="intake",
        lat=None,
        lon=None,
        source_provenance="test",
    )
    result = ingest_seeds([seed], snap_fn=lambda _lo, _la: _waters_fixture())
    assert result.assets == []
    assert len(result.review_items) == 1
    assert "missing coordinates" in result.review_items[0]["reason"]


def test_out_of_bbox_routes_to_review():
    bad = _ok_seed("AYL_AST_NYC", lat=40.7128, lon=-74.0060)
    result = ingest_seeds([bad], snap_fn=lambda _lo, _la: _waters_fixture())
    assert result.assets == []
    assert len(result.review_items) == 1
    assert "outside PR bbox" in result.review_items[0]["reason"]


def test_snap_exception_routes_to_review():
    def boom(_lo: float, _la: float) -> dict:
        raise RuntimeError("network down")

    result = ingest_seeds([_ok_seed("AYL_AST_NET")], snap_fn=boom)
    assert result.assets == []
    assert len(result.review_items) == 1
    assert "RuntimeError" in result.review_items[0]["reason"]


def test_non_utility_skipped_by_default():
    seed = FacilitySeed(
        seed_id="AYL_AST_HOSP",
        name="Bayamon Regional Hospital",
        municipality="Bayamon",
        asset_type="unknown",
        asset_subtype="facility",
        lat=18.367,
        lon=-66.154,
        is_utility=False,
        source_provenance="test",
    )
    result = ingest_seeds([seed], snap_fn=lambda _lo, _la: _waters_fixture())
    assert result.assets == []
    assert result.review_items == []
    assert len(result.skipped) == 1
    assert "non-utility" in result.skipped[0]["reason"]


def test_non_utility_processed_when_flag_disabled():
    seed = FacilitySeed(
        seed_id="AYL_AST_HOSP",
        name="Bayamon Regional Hospital",
        municipality="Bayamon",
        asset_type="unknown",
        asset_subtype="facility",
        lat=18.367,
        lon=-66.154,
        is_utility=False,
        source_provenance="test",
    )
    result = ingest_seeds(
        [seed], snap_fn=lambda _lo, _la: _waters_fixture(), skip_non_utility=False
    )
    assert len(result.assets) == 1
    assert result.skipped == []


def test_end_to_end_through_frs_fixture():
    """The FRS fixture has 3 utilities (with coords), 2 non-utilities (one of those null-coords),
    and 1 utility-like record with null coords. Verify counts add up."""
    seeds = parse_frs_response(
        json.loads((FIXTURES / "frs" / "pr_bayamon_npdes.json").read_text())
    )
    result = ingest_seeds(seeds, snap_fn=lambda _lo, _la: _waters_fixture())

    # 3 utility-classified seeds with valid coords → 3 assets
    assert len(result.assets) == 3
    # The non-utility records (APOLONIA APARTMENTS, BAYAMON CONCRETE IND, BAYAMON RGNL HOSPITAL)
    # get skipped — even the null-coords one, because skip_non_utility happens first.
    assert len(result.skipped) == 3
    # No review items in this fixture (all utility records have coords; non-utilities skipped).
    assert result.review_items == []
    # All three utility assets sit on VPU 21 → partial coverage.
    assert all(a["attribute_coverage"] == "partial" for a in result.assets)
    assert result.coverage_pct == 50.0  # 3 of 6 = 50%
