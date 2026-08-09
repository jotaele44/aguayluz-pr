#!/usr/bin/env python3
"""Build the local reference receipt for the provider-neutral spatial shadow pilot.

This benchmark deliberately excludes PR_SPIDERWEB_PIXEL_GRID_V1.  It uses only the
native world-space Puerto Rico municipio and barrio GeoJSON products generated from
U.S. Census Bureau cartographic boundary sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
import unicodedata
from pathlib import Path
from typing import Any

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "spatial_compute_shadow_v0_2.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def declared_geojson_crs(path: Path) -> str | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    crs = payload.get("crs")
    if not isinstance(crs, dict):
        return None
    props = crs.get("properties")
    if not isinstance(props, dict):
        return None
    value = props.get("name")
    return str(value) if value is not None else None


def norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return "".join(ch for ch in text if ch.isalnum())


def canonical_json_sha256(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def dataset_receipt(path: Path, frame: gpd.GeoDataFrame, id_field: str) -> dict[str, Any]:
    ids = frame[id_field].astype(str)
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "declared_geojson_crs": declared_geojson_crs(path),
        "runtime_crs": str(frame.crs),
        "feature_count": int(len(frame)),
        "geometry_types": sorted(frame.geometry.geom_type.unique().tolist()),
        "bounds": [float(v) for v in frame.total_bounds],
        "null_geometry_count": int(frame.geometry.isna().sum()),
        "empty_geometry_count": int(frame.geometry.is_empty.sum()),
        "invalid_geometry_count": int((~frame.geometry.is_valid).sum()),
        "duplicate_id_count": int(ids.duplicated().sum()),
    }


def require_dataset(
    frame: gpd.GeoDataFrame,
    *,
    name: str,
    expected_count: int,
    id_field: str,
    required_fields: tuple[str, ...],
) -> None:
    missing = [field for field in required_fields if field not in frame.columns]
    if missing:
        raise RuntimeError(f"{name}: missing required fields: {missing}")
    if len(frame) != expected_count:
        raise RuntimeError(f"{name}: expected {expected_count} features, found {len(frame)}")
    if frame.crs is None:
        raise RuntimeError(f"{name}: CRS is absent")
    if not bool(frame.crs.is_geographic):
        raise RuntimeError(f"{name}: expected native geographic CRS, found {frame.crs}")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise RuntimeError(f"{name}: null or empty geometry present")
    if (~frame.geometry.is_valid).any():
        raise RuntimeError(f"{name}: invalid geometry present")
    if frame[id_field].astype(str).duplicated().any():
        raise RuntimeError(f"{name}: duplicate {id_field} present")


def peak_memory_bytes() -> int:
    # Linux GitHub-hosted runners report ru_maxrss in KiB.
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="reports/spatial_compute/local_reference_receipt.json",
        help="Receipt path relative to repository root unless absolute.",
    )
    args = parser.parse_args()

    started = time.perf_counter()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    ref = config["reference_overlay"]

    left_path = ROOT / ref["left"]["path"]
    right_path = ROOT / ref["right"]["path"]
    municipios = gpd.read_file(left_path)
    barrios = gpd.read_file(right_path)

    require_dataset(
        municipios,
        name="municipios",
        expected_count=int(ref["left"]["expected_feature_count"]),
        id_field=ref["left"]["id_field"],
        required_fields=("geoid", "name", "geometry"),
    )
    require_dataset(
        barrios,
        name="barrios",
        expected_count=int(ref["right"]["expected_feature_count"]),
        id_field=ref["right"]["id_field"],
        required_fields=("geoid", "name", "municipio", "geometry"),
    )

    municipios = municipios.to_crs("EPSG:4326").copy()
    barrios = barrios.to_crs("EPSG:4326").copy()
    municipios["geoid"] = municipios["geoid"].astype(str)
    barrios["geoid"] = barrios["geoid"].astype(str)

    point_frame = gpd.GeoDataFrame(
        {
            "barrio_geoid": barrios["geoid"],
            "barrio_name": barrios["name"].astype(str),
            "declared_municipio": barrios["municipio"].astype(str),
        },
        geometry=barrios.geometry.representative_point(),
        crs=barrios.crs,
    )
    municipio_frame = municipios[["geoid", "name", "geometry"]].rename(
        columns={"geoid": "municipio_geoid", "name": "municipio_name"}
    )

    joined = gpd.sjoin(point_frame, municipio_frame, how="left", predicate="within")
    if joined["municipio_geoid"].isna().any():
        unresolved = joined.loc[joined["municipio_geoid"].isna(), "barrio_geoid"].tolist()
        raise RuntimeError(f"unresolved barrio point-on-surface parents: {unresolved[:20]}")

    cardinality = joined.groupby("barrio_geoid").size()
    non_unit = cardinality[cardinality != 1]
    if not non_unit.empty:
        raise RuntimeError(f"non-1:1 barrio parent cardinality: {non_unit.to_dict()}")
    if len(joined) != int(ref["expected_record_count"]):
        raise RuntimeError(
            f"expected {ref['expected_record_count']} joined records, found {len(joined)}"
        )

    joined["declared_parent_match"] = [
        norm_name(a) == norm_name(b)
        for a, b in zip(joined["declared_municipio"], joined["municipio_name"], strict=True)
    ]
    mismatches = joined.loc[~joined["declared_parent_match"]]
    if not mismatches.empty:
        cols = ["barrio_geoid", "declared_municipio", "municipio_name"]
        raise RuntimeError(f"declared/spatial parent mismatch: {mismatches[cols].to_dict('records')}")

    metric_crs = ref["computation_crs"]
    barrios_metric = barrios.to_crs(metric_crs).set_index("geoid", drop=False)
    municipios_metric = municipios.to_crs(metric_crs).set_index("geoid", drop=False)

    records: list[dict[str, Any]] = []
    for row in joined.sort_values("barrio_geoid").itertuples(index=False):
        barrio_geoid = str(row.barrio_geoid)
        municipio_geoid = str(row.municipio_geoid)
        barrio_geom = barrios_metric.loc[barrio_geoid].geometry
        municipio_geom = municipios_metric.loc[municipio_geoid].geometry
        intersection = barrio_geom.intersection(municipio_geom)
        barrio_area = float(barrio_geom.area)
        intersection_area = float(intersection.area)
        outside_area = max(0.0, barrio_area - intersection_area)
        coverage_ratio = intersection_area / barrio_area if barrio_area else 0.0
        point = barrio_geom.representative_point()
        boundary_distance = float(point.distance(municipio_geom.boundary))

        if barrio_geom.within(municipio_geom):
            topology = "FULL_WITHIN"
        elif municipio_geom.covers(barrio_geom):
            topology = "FULL_COVERED_BY"
        elif barrio_geom.intersects(municipio_geom):
            topology = "INTERSECTS"
        else:
            topology = "DISJOINT"

        records.append(
            {
                "barrio_geoid": barrio_geoid,
                "municipio_geoid": municipio_geoid,
                "barrio_name": str(row.barrio_name),
                "municipio_name": str(row.municipio_name),
                "declared_parent_match": bool(row.declared_parent_match),
                "topology_relation": topology,
                "barrio_area_m2": round(barrio_area, 6),
                "intersection_area_m2": round(intersection_area, 6),
                "outside_area_m2": round(outside_area, 6),
                "coverage_ratio": round(coverage_ratio, 12),
                "point_to_municipio_boundary_m": round(boundary_distance, 6),
                "intersection_wkb_sha256_local_diagnostic": hashlib.sha256(
                    intersection.wkb
                ).hexdigest(),
            }
        )

    semantic_rows = [
        {
            "barrio_geoid": row["barrio_geoid"],
            "municipio_geoid": row["municipio_geoid"],
            "declared_parent_match": row["declared_parent_match"],
            "topology_relation": row["topology_relation"],
        }
        for row in records
    ]
    topology_counts: dict[str, int] = {}
    for row in records:
        topology_counts[row["topology_relation"]] = topology_counts.get(row["topology_relation"], 0) + 1

    receipt = {
        "schema_version": "prii.spatial-compute-reference-receipt/v0.2",
        "status": "PASS",
        "provider": {
            "provider_name": "local_geopandas",
            "provider_version": gpd.__version__,
            "canonical_write_authority": False,
            "monetary_cost_usd": 0.0,
        },
        "contract": str(CONFIG_PATH.relative_to(ROOT)),
        "pixel_grid_used": False,
        "inputs": {
            "municipios": dataset_receipt(left_path, municipios, "geoid"),
            "barrios": dataset_receipt(right_path, barrios, "geoid"),
        },
        "operation": {
            "parent_join": ref["join_semantics"],
            "metric_geometry": ref["metric_geometry"],
            "computation_crs": metric_crs,
            "record_count": len(records),
            "declared_parent_match_count": sum(r["declared_parent_match"] for r in records),
            "topology_counts": topology_counts,
            "semantic_record_sha256": canonical_json_sha256(semantic_rows),
            "max_outside_area_m2": max(r["outside_area_m2"] for r in records),
            "max_outside_fraction": max(1.0 - r["coverage_ratio"] for r in records),
        },
        "numeric_tolerances": config["numeric_tolerances"],
        "runtime": {
            "runtime_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "peak_memory_bytes": peak_memory_bytes(),
        },
        "records": records,
    }

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": receipt["status"],
                "records": receipt["operation"]["record_count"],
                "semantic_record_sha256": receipt["operation"]["semantic_record_sha256"],
                "topology_counts": topology_counts,
                "max_outside_area_m2": receipt["operation"]["max_outside_area_m2"],
                "max_outside_fraction": receipt["operation"]["max_outside_fraction"],
                "runtime_ms": receipt["runtime"]["runtime_ms"],
                "peak_memory_bytes": receipt["runtime"]["peak_memory_bytes"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
