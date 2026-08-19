#!/usr/bin/env python3
"""Fail-closed Puerto Rico municipio boundary validation.

Reports geometry validity, layer relationships, adjacency-graph topology, and
78-municipio administrative topology as independent validation classes.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import CRS
from shapely import coverage_invalid_edges, coverage_is_valid
from shapely.geometry import Point
from shapely.validation import explain_validity

CLASS_NAMES = (
    "GEOMETRY_VALIDITY",
    "LAYER_RELATIONSHIP_TOPOLOGY",
    "NETWORK_GRAPH_TOPOLOGY",
    "ADMINISTRATIVE_BOUNDARY_TOPOLOGY",
)
ALLOWED_TYPES = {"Polygon", "MultiPolygon"}
DEFAULT_ISLAND_GEOIDS = frozenset({"72049", "72147"})  # Culebra, Vieques


def _class_result(name: str) -> dict[str, Any]:
    return {"validation_class": name, "status": "PASS", "checks": [], "findings": [], "metrics": {}}


def _fail(result: dict[str, Any], code: str, message: str, **details: Any) -> None:
    result["status"] = "FAILED_VALIDATION"
    result["findings"].append({"code": code, "message": message, **details})


def _raw_crs(path: Path) -> tuple[dict[str, Any], str | None]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON root must be a FeatureCollection")
    crs = raw.get("crs")
    if isinstance(crs, dict):
        props = crs.get("properties")
        if isinstance(props, dict) and isinstance(props.get("name"), str):
            return raw, props["name"].strip() or None
    return raw, None


def _registry(path: Path) -> dict[str, tuple[float, float]]:
    rows = json.loads(path.read_text(encoding="utf-8")).get("municipios")
    if not isinstance(rows, list):
        raise ValueError("registry must contain a municipios list")
    result: dict[str, tuple[float, float]] = {}
    for row in rows:
        name = str(row["name"])
        if name in result:
            raise ValueError(f"duplicate registry municipio: {name}")
        result[name] = (float(row["lon"]), float(row["lat"]))
    return result


def _pairs(gdf: gpd.GeoDataFrame):
    seen: set[tuple[int, int]] = set()
    for left, geom in enumerate(gdf.geometry):
        for right_value in gdf.sindex.query(geom, predicate="intersects"):
            right = int(right_value)
            pair = (left, right)
            if right > left and pair not in seen:
                seen.add(pair)
                yield pair


def _components(nodes: set[str], adjacency: dict[str, set[str]]) -> list[set[str]]:
    pending = set(nodes)
    result: list[set[str]] = []
    while pending:
        queue: deque[str] = deque([min(pending)])
        component: set[str] = set()
        while queue:
            node = queue.popleft()
            if node in component:
                continue
            component.add(node)
            queue.extend(sorted(adjacency.get(node, set()) - component))
        result.append(component)
        pending -= component
    return sorted(result, key=lambda value: (-len(value), sorted(value)))


def _geometry(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    result = _class_result("GEOMETRY_VALIDITY")
    result["checks"] = ["non-null/non-empty", "Polygon or MultiPolygon", "Shapely validity"]
    for _, row in gdf.iterrows():
        geoid = str(row.get("geoid", "unknown"))
        geom = row.geometry
        if geom is None or geom.is_empty:
            _fail(result, "empty_geometry", "geometry is null or empty", feature_ids=[geoid])
            continue
        if geom.geom_type not in ALLOWED_TYPES:
            _fail(result, "unsupported_geometry_type", geom.geom_type, feature_ids=[geoid])
        if not geom.is_valid:
            _fail(result, "invalid_geometry", explain_validity(geom), feature_ids=[geoid])
    result["metrics"] = {"feature_count": len(gdf), "finding_count": len(result["findings"])}
    return result


def _layer(projected: gpd.GeoDataFrame, overlap_m2: float, gap_m: float) -> dict[str, Any]:
    result = _class_result("LAYER_RELATIONSHIP_TOPOLOGY")
    result["checks"] = ["coverage gaps/overlaps", "pairwise overlap", "cross-feature containment"]
    geoms = list(projected.geometry)
    coverage_ok = bool(coverage_is_valid(geoms, gap_width=gap_m))
    invalid_edges = sum(not edge.is_empty for edge in coverage_invalid_edges(geoms, gap_width=gap_m))
    if not coverage_ok:
        _fail(result, "coverage_invalid", "coverage contains overlap or internal gap", invalid_edge_count=invalid_edges)

    overlap_pairs = 0
    containment_pairs = 0
    max_overlap = 0.0
    for left, right in _pairs(projected):
        a = projected.iloc[left]
        b = projected.iloc[right]
        ids = [str(a["geoid"]), str(b["geoid"])]
        if a.geometry.contains(b.geometry) or b.geometry.contains(a.geometry):
            containment_pairs += 1
            _fail(result, "cross_feature_containment", "one municipio contains another", feature_ids=ids)
        area = float(a.geometry.intersection(b.geometry).area)
        max_overlap = max(max_overlap, area)
        if area > overlap_m2:
            overlap_pairs += 1
            _fail(result, "polygon_overlap", "overlap exceeds tolerance", feature_ids=ids, overlap_area_m2=area)
    result["metrics"] = {
        "coverage_is_valid": coverage_ok,
        "invalid_edge_count": invalid_edges,
        "overlap_pair_count": overlap_pairs,
        "containment_pair_count": containment_pairs,
        "maximum_overlap_m2": max_overlap,
        "overlap_tolerance_m2": overlap_m2,
        "gap_width_m": gap_m,
    }
    return result


def _network(
    projected: gpd.GeoDataFrame,
    isolated_geoids: frozenset[str],
    minimum_shared_boundary_m: float,
) -> tuple[dict[str, Any], dict[str, set[str]]]:
    result = _class_result("NETWORK_GRAPH_TOPOLOGY")
    result["checks"] = ["shared-line adjacency", "one mainland component", "only allowed islands isolated"]
    nodes = {str(value) for value in projected["geoid"]}
    adjacency: dict[str, set[str]] = defaultdict(set)
    edges = 0
    for left, right in _pairs(projected):
        a = projected.iloc[left]
        b = projected.iloc[right]
        shared = float(a.geometry.boundary.intersection(b.geometry.boundary).length)
        if shared > minimum_shared_boundary_m:
            aid, bid = str(a["geoid"]), str(b["geoid"])
            adjacency[aid].add(bid)
            adjacency[bid].add(aid)
            edges += 1

    components = _components(nodes, adjacency)
    isolated = {next(iter(item)) for item in components if len(item) == 1}
    mainland = nodes - isolated_geoids
    mainland_components = [item & mainland for item in components if item & mainland]
    if mainland and len(mainland_components) != 1:
        _fail(result, "mainland_graph_disconnected", "non-island municipios are disconnected", component_count=len(mainland_components))
    unexpected = sorted(isolated - isolated_geoids)
    missing_islands = sorted(isolated_geoids - nodes)
    if unexpected:
        _fail(result, "unexpected_isolated_municipio", "unexpected isolated graph node", feature_ids=unexpected)
    if missing_islands:
        _fail(result, "configured_island_missing", "configured island GEOID missing", feature_ids=missing_islands)
    result["metrics"] = {
        "node_count": len(nodes),
        "edge_count": edges,
        "component_count": len(components),
        "component_sizes": [len(item) for item in components],
        "isolated_geoids": sorted(isolated),
        "allowed_isolated_geoids": sorted(isolated_geoids),
        "minimum_shared_boundary_m": minimum_shared_boundary_m,
    }
    return result, adjacency


def _administrative(
    gdf: gpd.GeoDataFrame,
    registry: dict[str, tuple[float, float]],
    adjacency: dict[str, set[str]],
    expected_count: int,
    isolated_geoids: frozenset[str],
) -> dict[str, Any]:
    result = _class_result("ADMINISTRATIVE_BOUNDARY_TOPOLOGY")
    result["checks"] = ["78 features", "unique PR GEOIDs/names", "registry parity", "Census internal points", "non-island adjacency"]
    if len(gdf) != expected_count:
        _fail(result, "feature_count_mismatch", f"expected {expected_count}, found {len(gdf)}")
    geoids = [str(value) for value in gdf["geoid"]]
    names = [str(value) for value in gdf["name"]]
    duplicates = sorted({value for value in geoids if geoids.count(value) > 1})
    duplicate_names = sorted({value for value in names if names.count(value) > 1})
    invalid_geoids = sorted(value for value in geoids if len(value) != 5 or not value.startswith("72"))
    if duplicates:
        _fail(result, "duplicate_geoid", "GEOIDs must be unique", feature_ids=duplicates)
    if duplicate_names:
        _fail(result, "duplicate_name", "names must be unique", feature_ids=duplicate_names)
    if invalid_geoids:
        _fail(result, "invalid_pr_geoid", "GEOID must be five digits with prefix 72", feature_ids=invalid_geoids)

    boundary_names, registry_names = set(names), set(registry)
    missing = sorted(registry_names - boundary_names)
    extra = sorted(boundary_names - registry_names)
    if missing:
        _fail(result, "registry_name_missing", "registry municipio missing from boundaries", feature_ids=missing)
    if extra:
        _fail(result, "unexpected_boundary_name", "boundary absent from registry", feature_ids=extra)

    by_name = {str(row["name"]): row for _, row in gdf.iterrows()}
    outside: list[str] = []
    for name in sorted(boundary_names & registry_names):
        lon, lat = registry[name]
        if not by_name[name].geometry.covers(Point(lon, lat)):
            outside.append(name)
    if outside:
        _fail(result, "internal_point_outside_boundary", "Census internal point outside named municipio", feature_ids=outside)

    omissions = sorted(geoid for geoid in set(geoids) - isolated_geoids if not adjacency.get(geoid))
    if omissions:
        _fail(result, "non_island_without_adjacency", "non-island municipio has no graph edge", feature_ids=omissions)
    result["metrics"] = {
        "expected_count": expected_count,
        "actual_count": len(gdf),
        "unique_geoid_count": len(set(geoids)),
        "unique_name_count": len(set(names)),
        "registry_name_count": len(registry_names),
        "internal_points_checked": len(boundary_names & registry_names),
        "internal_points_outside_count": len(outside),
    }
    return result


def validate_boundaries(
    boundaries: Path,
    registry_path: Path,
    *,
    output_class: str = "authoritative",
    assume_crs: str | None = None,
    positional_uncertainty_m: float | None = None,
    expected_count: int = 78,
    isolated_geoids: frozenset[str] = DEFAULT_ISLAND_GEOIDS,
    projected_crs: str = "EPSG:32161",
    overlap_tolerance_m2: float = 1.0,
    gap_width_m: float = 1.0,
    minimum_shared_boundary_m: float = 1.0,
) -> dict[str, Any]:
    _, declared_crs = _raw_crs(boundaries)
    classes = {name: _class_result(name) for name in CLASS_NAMES}
    authoritative = output_class in {"authoritative", "decision_relevant"}
    if declared_crs is None and authoritative:
        _fail(classes["GEOMETRY_VALIDITY"], "authoritative_crs_missing", "authoritative CRS missing; no default assigned")
        for name in CLASS_NAMES[1:]:
            classes[name]["status"] = "NOT_EVALUATED"
            classes[name]["findings"] = [{"code": "blocked_by_missing_crs", "message": "not evaluated"}]
        return _report(boundaries, output_class, None, None, False, positional_uncertainty_m, classes)

    assumed = declared_crs is None
    if assumed:
        if not assume_crs:
            raise ValueError("synthetic/experimental missing CRS requires --assume-crs")
        if positional_uncertainty_m is None or positional_uncertainty_m <= 0:
            raise ValueError("synthetic/experimental missing CRS requires positive --positional-uncertainty-m")
        effective_crs = CRS.from_user_input(assume_crs).to_string()
    else:
        effective_crs = CRS.from_user_input(declared_crs).to_string()

    gdf = gpd.read_file(boundaries).set_crs(effective_crs, allow_override=True)
    missing_fields = sorted({"geoid", "name"} - set(gdf.columns))
    if missing_fields:
        _fail(classes["ADMINISTRATIVE_BOUNDARY_TOPOLOGY"], "required_attribute_missing", ", ".join(missing_fields))
        return _report(boundaries, output_class, declared_crs, effective_crs, assumed, positional_uncertainty_m, classes)

    classes["GEOMETRY_VALIDITY"] = _geometry(gdf)
    if classes["GEOMETRY_VALIDITY"]["status"] != "PASS":
        for name in CLASS_NAMES[1:]:
            classes[name]["status"] = "NOT_EVALUATED"
            classes[name]["findings"] = [{"code": "blocked_by_geometry_failure", "message": "not evaluated"}]
        return _report(boundaries, output_class, declared_crs, effective_crs, assumed, positional_uncertainty_m, classes)

    projected = gdf.to_crs(projected_crs)
    classes["LAYER_RELATIONSHIP_TOPOLOGY"] = _layer(projected, overlap_tolerance_m2, gap_width_m)
    classes["NETWORK_GRAPH_TOPOLOGY"], adjacency = _network(projected, isolated_geoids, minimum_shared_boundary_m)
    classes["ADMINISTRATIVE_BOUNDARY_TOPOLOGY"] = _administrative(
        gdf, _registry(registry_path), adjacency, expected_count, isolated_geoids
    )
    return _report(boundaries, output_class, declared_crs, effective_crs, assumed, positional_uncertainty_m, classes)


def _report(
    source: Path,
    output_class: str,
    declared_crs: str | None,
    effective_crs: str | None,
    assumed_crs: bool,
    positional_uncertainty_m: float | None,
    classes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    passed = all(value["status"] == "PASS" for value in classes.values())
    return {
        "source": str(source),
        "output_class": output_class,
        "declared_crs": declared_crs,
        "effective_crs": effective_crs,
        "assumed_crs": assumed_crs,
        "positional_uncertainty_m": positional_uncertainty_m,
        "classes": classes,
        "passed": passed,
        "overall_status": "PASS" if passed else "FAILED_VALIDATION",
        "terminal_state": "COMPLETE" if passed else "FAILED_VALIDATION",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("boundaries", type=Path)
    parser.add_argument("--registry", type=Path, default=Path("data/geo/pr_municipios.json"))
    parser.add_argument("--output-class", choices=["authoritative", "decision_relevant", "synthetic", "experimental"], default="authoritative")
    parser.add_argument("--assume-crs")
    parser.add_argument("--positional-uncertainty-m", type=float)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--overlap-tolerance-m2", type=float, default=1.0)
    parser.add_argument("--gap-width-m", type=float, default=1.0)
    parser.add_argument("--minimum-shared-boundary-m", type=float, default=1.0)
    args = parser.parse_args()
    report = validate_boundaries(
        args.boundaries,
        args.registry,
        output_class=args.output_class,
        assume_crs=args.assume_crs,
        positional_uncertainty_m=args.positional_uncertainty_m,
        overlap_tolerance_m2=args.overlap_tolerance_m2,
        gap_width_m=args.gap_width_m,
        minimum_shared_boundary_m=args.minimum_shared_boundary_m,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
