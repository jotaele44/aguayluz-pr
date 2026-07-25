"""Tests for the infrastructure-impact linkage helpers (aguayluz.impact)."""

from __future__ import annotations

from aguayluz.impact import (
    SECTOR_FOR_ASSET_TYPE,
    AssetIndex,
    _haversine_km,
    build_asset_index,
    in_alert_bounds,
    link_impact,
    merge_asset_ids,
)

# A small asset corpus: two geocoded Bayamón assets (water + power), one
# coordinate-less Ponce wastewater asset, one geocoded catch-all-municipality water
# asset, and one asset of an unmodelled type that must be dropped entirely.
ASSETS = [
    {"asset_id": "W1", "asset_type": "water", "lat": 18.40, "lon": -66.15, "municipality": "Bayamón"},
    {"asset_id": "P1", "asset_type": "power", "lat": 18.42, "lon": -66.15, "municipality": "Bayamón"},
    {"asset_id": "WW1", "asset_type": "wastewater", "municipality": "Ponce"},
    {"asset_id": "C1", "asset_type": "water", "lat": 18.011, "lon": -66.614, "municipality": "Puerto Rico"},
    {"asset_id": "T1", "asset_type": "telecom", "lat": 18.4, "lon": -66.1, "municipality": "Bayamón"},
]
INDEX = build_asset_index(ASSETS)


def test_haversine_known_distance():
    # San Juan -> Ponce is ~73-74 km.
    d = _haversine_km(18.4655, -66.1057, 18.0111, -66.6141)
    assert 70 < d < 78


def test_build_index_drops_unmodelled_types_and_placeholder_municipality():
    ids = {aid for aid, *_ in INDEX.geocoded}
    assert ids == {"W1", "P1", "C1"}  # T1 (telecom) dropped, WW1 has no coords
    assert set(INDEX.by_municipality) == {"BAYAMON", "PONCE"}  # "Puerto Rico" excluded
    assert {aid for aid, _ in INDEX.by_municipality["BAYAMON"]} == {"W1", "P1"}


def test_radius_match_returns_ids_and_sectors():
    linked, sectors = link_impact(18.41, -66.15, None, INDEX, radius_km=5.0)
    assert linked == ["P1", "W1"]  # sorted, both within 5 km
    assert sectors == ["power", "water"]  # sorted unique


def test_radius_match_excludes_far_assets():
    # A point off the west coast: nothing within 5 km.
    linked, sectors = link_impact(18.30, -67.20, None, INDEX, radius_km=5.0)
    assert linked == [] and sectors == []


def test_municipality_fallback_when_no_coordinates():
    linked, sectors = link_impact(None, None, ["Ponce"], INDEX, radius_km=None)
    assert linked == ["WW1"] and sectors == ["wastewater"]


def test_accented_municipality_matches():
    linked, _ = link_impact(None, None, ["Bayamón"], INDEX, radius_km=None)
    assert set(linked) == {"W1", "P1"}


def test_unknown_municipality_and_unscoped_yield_nothing():
    assert link_impact(None, None, ["Nowhere"], INDEX, radius_km=None) == ([], [])
    assert link_impact(None, None, ["(unscoped)"], INDEX, radius_km=None) == ([], [])


def test_empty_index_yields_nothing():
    assert link_impact(18.41, -66.15, ["Bayamón"], AssetIndex(), radius_km=5.0) == ([], [])


def test_max_assets_caps_ids_but_not_sectors():
    many = [
        {"asset_id": f"W{i}", "asset_type": "water", "lat": 18.40, "lon": -66.15, "municipality": "X"}
        for i in range(10)
    ]
    many.append({"asset_id": "P9", "asset_type": "power", "lat": 18.40, "lon": -66.15, "municipality": "X"})
    idx = build_asset_index(many)
    linked, sectors = link_impact(18.40, -66.15, None, idx, radius_km=1.0, max_assets=3)
    assert len(linked) == 3  # id list capped
    assert sectors == ["power", "water"]  # sectors still reflect the full match set


def test_coordinate_path_used_only_when_radius_present():
    # lat/lon present but radius None -> municipality path (coords ignored).
    linked, _ = link_impact(18.40, -66.15, ["Ponce"], INDEX, radius_km=None)
    assert linked == ["WW1"]


def test_in_alert_bounds():
    assert in_alert_bounds(18.2, -66.5) is True
    assert in_alert_bounds(17.6, -66.5) is False  # offshore south (below 17.7)
    assert in_alert_bounds(None, -66.5) is False


def test_merge_asset_ids_dedupes_and_sorts():
    assert merge_asset_ids(["b", "a"], ["a", "c"]) == ["a", "b", "c"]
    assert merge_asset_ids(None, None) == []


def test_sector_map_covers_corpus_types():
    assert SECTOR_FOR_ASSET_TYPE == {"water": "water", "wastewater": "wastewater", "power": "power"}
