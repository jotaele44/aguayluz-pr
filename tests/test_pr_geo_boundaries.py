"""Validate committed and synthetic Puerto Rico boundary layers."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from shapely.geometry import Polygon, mapping

from aguayluz import REPO_ROOT

MUNI = REPO_ROOT / "data/geo/pr_municipios.geojson"
BARRIOS = REPO_ROOT / "data/geo/pr_barrios.geojson"
CENTROIDS = REPO_ROOT / "data/geo/pr_municipios.json"
MODULE_PATH = REPO_ROOT / "scripts" / "validate_pr_geo_boundaries.py"
SPEC = importlib.util.spec_from_file_location("validate_pr_geo_boundaries", MODULE_PATH)
assert SPEC and SPEC.loader
geo = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = geo
SPEC.loader.exec_module(geo)


def _features(path: Path) -> list:
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["type"] == "FeatureCollection"
    return doc["features"]


def _feature(name: str, geoid: str, polygon: Polygon) -> dict:
    return {
        "type": "Feature",
        "properties": {"name": name, "geoid": geoid},
        "geometry": mapping(polygon),
    }


def _write_geojson(path: Path, features: list[dict], *, include_crs: bool = True) -> None:
    payload: dict = {"type": "FeatureCollection", "features": features}
    if include_crs:
        payload["crs"] = {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_registry(path: Path, rows: list[tuple[str, float, float]]) -> None:
    payload = {
        "_source": "test fixture",
        "municipios": [{"name": name, "lon": lon, "lat": lat} for name, lon, lat in rows],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _grid_fixture(tmp_path: Path) -> tuple[Path, Path]:
    boundaries = tmp_path / "grid.geojson"
    registry = tmp_path / "registry.json"
    features = [
        _feature("A", "72001", Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])),
        _feature("B", "72003", Polygon([(1, 0), (2, 0), (2, 1), (1, 1), (1, 0)])),
        _feature("C", "72005", Polygon([(0, 1), (1, 1), (1, 2), (0, 2), (0, 1)])),
        _feature("D", "72007", Polygon([(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)])),
    ]
    _write_geojson(boundaries, features)
    _write_registry(
        registry,
        [("A", 0.5, 0.5), ("B", 1.5, 0.5), ("C", 0.5, 1.5), ("D", 1.5, 1.5)],
    )
    return boundaries, registry


def test_municipio_polygons():
    feats = _features(MUNI)
    assert len(feats) == 78
    for feature in feats:
        assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert feature["properties"]["name"]
        assert feature["properties"]["geoid"].startswith("72")


def test_barrios_link_to_municipios():
    munis = {feature["properties"]["name"] for feature in _features(MUNI)}
    barrios = _features(BARRIOS)
    assert len(barrios) > 800
    parents = {feature["properties"]["municipio"] for feature in barrios}
    assert parents <= munis


def test_polygon_and_centroid_layers_share_names():
    munis = {feature["properties"]["name"] for feature in _features(MUNI)}
    centroids = {row["name"] for row in json.loads(CENTROIDS.read_text())["municipios"]}
    assert munis == centroids


def test_authoritative_missing_crs_fails_closed(tmp_path: Path) -> None:
    boundaries = tmp_path / "missing-crs.geojson"
    registry = tmp_path / "registry.json"
    _write_geojson(
        boundaries,
        [_feature("A", "72001", Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]))],
        include_crs=False,
    )
    _write_registry(registry, [("A", 0.5, 0.5)])

    report = geo.validate_boundaries(
        boundaries,
        registry,
        output_class="authoritative",
        expected_count=1,
        isolated_geoids=frozenset({"72001"}),
    )

    assert report["terminal_state"] == "FAILED_VALIDATION"
    assert report["assumed_crs"] is False
    assert report["effective_crs"] is None
    assert report["classes"]["GEOMETRY_VALIDITY"]["status"] == "FAILED_VALIDATION"
    assert report["classes"]["LAYER_RELATIONSHIP_TOPOLOGY"]["status"] == "NOT_EVALUATED"
    assert any(
        finding["code"] == "authoritative_crs_missing"
        for finding in report["classes"]["GEOMETRY_VALIDITY"]["findings"]
    )


def test_synthetic_missing_crs_requires_explicit_assumption_and_uncertainty(
    tmp_path: Path,
) -> None:
    boundaries = tmp_path / "synthetic.geojson"
    registry = tmp_path / "registry.json"
    _write_geojson(
        boundaries,
        [_feature("A", "72001", Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]))],
        include_crs=False,
    )
    _write_registry(registry, [("A", 0.5, 0.5)])

    with pytest.raises(ValueError, match="requires --assume-crs"):
        geo.validate_boundaries(
            boundaries,
            registry,
            output_class="synthetic",
            expected_count=1,
            isolated_geoids=frozenset({"72001"}),
        )

    with pytest.raises(ValueError, match="positive --positional-uncertainty-m"):
        geo.validate_boundaries(
            boundaries,
            registry,
            output_class="synthetic",
            assume_crs="EPSG:4326",
            expected_count=1,
            isolated_geoids=frozenset({"72001"}),
        )

    report = geo.validate_boundaries(
        boundaries,
        registry,
        output_class="synthetic",
        assume_crs="EPSG:4326",
        positional_uncertainty_m=50.0,
        expected_count=1,
        isolated_geoids=frozenset({"72001"}),
    )
    assert report["passed"]
    assert report["assumed_crs"] is True
    assert report["positional_uncertainty_m"] == 50.0


def test_all_four_classes_pass_independently_on_complete_grid(tmp_path: Path) -> None:
    boundaries, registry = _grid_fixture(tmp_path)
    report = geo.validate_boundaries(
        boundaries,
        registry,
        expected_count=4,
        isolated_geoids=frozenset(),
        projected_crs="EPSG:3857",
        overlap_tolerance_m2=0.01,
        gap_width_m=0.01,
        minimum_shared_boundary_m=1.0,
    )
    assert report["passed"]
    assert {name: result["status"] for name, result in report["classes"].items()} == {
        "GEOMETRY_VALIDITY": "PASS",
        "LAYER_RELATIONSHIP_TOPOLOGY": "PASS",
        "NETWORK_GRAPH_TOPOLOGY": "PASS",
        "ADMINISTRATIVE_BOUNDARY_TOPOLOGY": "PASS",
    }


def test_network_failure_does_not_relabel_other_topology_classes(tmp_path: Path) -> None:
    boundaries = tmp_path / "disconnected.geojson"
    registry = tmp_path / "registry.json"
    _write_geojson(
        boundaries,
        [
            _feature("A", "72001", Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])),
            _feature("B", "72003", Polygon([(3, 0), (4, 0), (4, 1), (3, 1), (3, 0)])),
        ],
    )
    _write_registry(registry, [("A", 0.5, 0.5), ("B", 3.5, 0.5)])
    report = geo.validate_boundaries(
        boundaries,
        registry,
        expected_count=2,
        isolated_geoids=frozenset(),
        projected_crs="EPSG:3857",
    )
    assert report["classes"]["GEOMETRY_VALIDITY"]["status"] == "PASS"
    assert report["classes"]["LAYER_RELATIONSHIP_TOPOLOGY"]["status"] == "PASS"
    assert report["classes"]["NETWORK_GRAPH_TOPOLOGY"]["status"] == "FAILED_VALIDATION"
    assert report["classes"]["ADMINISTRATIVE_BOUNDARY_TOPOLOGY"]["status"] == "FAILED_VALIDATION"


def test_registry_mismatch_only_fails_administrative_class(tmp_path: Path) -> None:
    boundaries, registry = _grid_fixture(tmp_path)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["municipios"][0]["name"] = "Wrong Name"
    registry.write_text(json.dumps(payload), encoding="utf-8")
    report = geo.validate_boundaries(
        boundaries,
        registry,
        expected_count=4,
        isolated_geoids=frozenset(),
        projected_crs="EPSG:3857",
    )
    assert report["classes"]["GEOMETRY_VALIDITY"]["status"] == "PASS"
    assert report["classes"]["LAYER_RELATIONSHIP_TOPOLOGY"]["status"] == "PASS"
    assert report["classes"]["NETWORK_GRAPH_TOPOLOGY"]["status"] == "PASS"
    assert report["classes"]["ADMINISTRATIVE_BOUNDARY_TOPOLOGY"]["status"] == "FAILED_VALIDATION"


def test_invalid_geometry_blocks_dependent_classes(tmp_path: Path) -> None:
    boundaries = tmp_path / "invalid.geojson"
    registry = tmp_path / "registry.json"
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    _write_geojson(boundaries, [_feature("A", "72001", bowtie)])
    _write_registry(registry, [("A", 0.5, 0.5)])
    report = geo.validate_boundaries(
        boundaries,
        registry,
        expected_count=1,
        isolated_geoids=frozenset({"72001"}),
        projected_crs="EPSG:3857",
    )
    assert report["classes"]["GEOMETRY_VALIDITY"]["status"] == "FAILED_VALIDATION"
    assert report["classes"]["LAYER_RELATIONSHIP_TOPOLOGY"]["status"] == "NOT_EVALUATED"
    assert report["classes"]["NETWORK_GRAPH_TOPOLOGY"]["status"] == "NOT_EVALUATED"
    assert report["classes"]["ADMINISTRATIVE_BOUNDARY_TOPOLOGY"]["status"] == "NOT_EVALUATED"
