"""Tests for the HIFLD GeoJSON adapter + HTTP client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from aguayluz.ingest.hifld import (
    _centroid_point,
    _snap_coords_from_geometry,
    parse_hifld_geojson,
)
from aguayluz.ingest.hifld_client import (
    LAYER_URLS,
    HIFLDClientError,
    fetch_layer,
)

FIXTURES = Path(__file__).parent / "fixtures" / "hifld"


def _load() -> dict:
    return json.loads((FIXTURES / "pr_substations_sample.geojson").read_text(encoding="utf-8"))


# ---------- geometry helpers ----------


def test_centroid_point_simple_mean():
    assert _centroid_point([[0.0, 0.0], [10.0, 10.0]]) == (5.0, 5.0)


def test_centroid_point_empty_returns_origin():
    assert _centroid_point([]) == (0.0, 0.0)


def test_snap_coords_point():
    g = {"type": "Point", "coordinates": [-66.232, 18.388]}
    assert _snap_coords_from_geometry(g) == ("point", -66.232, 18.388)


def test_snap_coords_linestring_uses_centroid():
    g = {"type": "LineString", "coordinates": [[-66.1, 18.2], [-66.3, 18.4]]}
    gtype, lon, lat = _snap_coords_from_geometry(g)
    assert gtype == "line"
    assert lon == pytest.approx(-66.2)
    assert lat == pytest.approx(18.3)


def test_snap_coords_polygon_uses_first_ring_centroid():
    g = {
        "type": "Polygon",
        "coordinates": [[
            [-66.0, 18.0], [-66.0, 19.0], [-65.0, 19.0], [-65.0, 18.0], [-66.0, 18.0],
        ]],
    }
    gtype, lon, lat = _snap_coords_from_geometry(g)
    assert gtype == "polygon"
    # Mean of 5 points (closed ring), but coords are symmetric → centroid ≈ (-65.6, 18.4)
    assert lon == pytest.approx(-65.6, abs=1e-3)
    assert lat == pytest.approx(18.4, abs=1e-3)


def test_snap_coords_unknown_geometry_returns_nulls():
    assert _snap_coords_from_geometry({"type": "WhatEver"}) == ("unknown", None, None)
    assert _snap_coords_from_geometry({}) == ("unknown", None, None)


# ---------- parse_hifld_geojson ----------


def test_parse_hifld_keeps_only_pr_features_by_default():
    seeds = parse_hifld_geojson(_load())
    # Fixture has 6 features; 1 is in FL (filtered out).
    assert len(seeds) == 5


def test_parse_hifld_state_filter_disabled():
    seeds = parse_hifld_geojson(_load(), state_filter=None)
    assert len(seeds) == 6


def test_parse_hifld_classifies_by_name():
    seeds = parse_hifld_geojson(_load())
    by_name = {s.name: s for s in seeds}
    assert by_name["LUMA CATANO SUBSTATION"].asset_type == "power"
    assert by_name["LUMA CATANO SUBSTATION"].asset_subtype == "substation"
    assert by_name["PRASA SUPERAQUEDUCT WATER TREATMENT PLANT"].asset_type == "water"
    assert by_name["PRASA SUPERAQUEDUCT WATER TREATMENT PLANT"].asset_subtype == "treatment_plant"


def test_parse_hifld_propagates_geometry_type():
    seeds = parse_hifld_geojson(_load())
    by_name = {s.name: s for s in seeds}
    assert by_name["LUMA CATANO SUBSTATION"].geometry_type == "point"
    assert by_name["AGUAS BUENAS - CAGUAS 115KV TRANSMISSION LINE"].geometry_type == "line"
    assert by_name["PRASA SUPERAQUEDUCT WATER TREATMENT PLANT"].geometry_type == "polygon"


def test_parse_hifld_line_lat_lon_is_centroid():
    seeds = parse_hifld_geojson(_load())
    line = next(s for s in seeds if s.geometry_type == "line")
    # Fixture line coords: [-66.1031, 18.2566], [-66.0807, 18.2384], [-66.0353, 18.2345]
    assert line.lon == pytest.approx(-66.0730, abs=1e-3)
    assert line.lat == pytest.approx(18.2432, abs=1e-3)


def test_parse_hifld_picks_owner_as_operator():
    seeds = parse_hifld_geojson(_load())
    luma = next(s for s in seeds if s.name == "LUMA CATANO SUBSTATION")
    assert luma.operator == "LUMA Energy"


def test_parse_hifld_seed_id_uses_hifld_prefix():
    seeds = parse_hifld_geojson(_load())
    assert all(s.seed_id.startswith("AYL_AST_HIFLD_") for s in seeds)


def test_parse_hifld_provenance_set():
    seeds = parse_hifld_geojson(_load())
    assert all("HIFLD" in s.source_provenance for s in seeds)


def test_parse_hifld_empty_collection():
    assert parse_hifld_geojson({"features": []}) == []
    assert parse_hifld_geojson({}) == []


# ---------- hifld_client ----------


def test_fetch_layer_unknown_layer_raises():
    with pytest.raises(HIFLDClientError, match="unknown layer"):
        fetch_layer(layer="nonsense_layer")


def test_fetch_layer_live_success(httpx_mock):
    payload = {"type": "FeatureCollection", "features": []}
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    result = fetch_layer(layer="electric_substations", fallback_path=None)
    assert result == payload


def test_fetch_layer_falls_back_on_arcgis_error(httpx_mock, tmp_path):
    # ArcGIS often returns HTTP 200 with an `error` object on bad queries.
    httpx_mock.add_response(method="GET", json={"error": {"code": 400, "message": "bad"}}, status_code=200)
    fallback = tmp_path / "fallback.geojson"
    fallback.write_text('{"type": "FeatureCollection", "features": [{"i": 1}]}', encoding="utf-8")
    result = fetch_layer(layer="electric_substations", fallback_path=fallback)
    assert result["features"] == [{"i": 1}]


def test_fetch_layer_falls_back_on_http_error(httpx_mock, tmp_path):
    httpx_mock.add_response(method="GET", status_code=404, text="not found")
    fallback = tmp_path / "fb.geojson"
    fallback.write_text('{"features": []}', encoding="utf-8")
    result = fetch_layer(layer="electric_substations", fallback_path=fallback)
    assert "features" in result


def test_fetch_layer_no_fallback_raises_on_http_error(httpx_mock):
    httpx_mock.add_response(method="GET", status_code=404, text="not found")
    with pytest.raises(HIFLDClientError, match="HIFLD HTTP 404"):
        fetch_layer(layer="electric_substations", fallback_path=None)


def test_fetch_layer_missing_fallback_raises(httpx_mock, tmp_path):
    httpx_mock.add_response(method="GET", status_code=503, text="boom")
    with pytest.raises(HIFLDClientError, match="fallback snapshot missing"):
        fetch_layer(layer="electric_substations", fallback_path=tmp_path / "nope.geojson")


def test_fetch_layer_uses_injected_client(httpx_mock):
    httpx_mock.add_response(method="GET", json={"type": "FeatureCollection", "features": []}, status_code=200)
    with httpx.Client() as client:
        fetch_layer(layer="electric_substations", client=client, fallback_path=None)


def test_known_layer_urls_are_strings():
    assert all(isinstance(url, str) and url.startswith("https://") for url in LAYER_URLS.values())
