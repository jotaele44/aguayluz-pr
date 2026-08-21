#!/usr/bin/env python3
"""Execute the native world-space reference contract with Apache Sedona.

This is a local compatibility gate for the same Sedona Spatial SQL semantics used by the
managed Wherobots provider. It does not constitute a Wherobots Cloud execution receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import time
import unicodedata
from pathlib import Path
from typing import Any

import pyspark
from sedona.spark import SedonaContext

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "spatial_compute_shadow_v0_2.json"
SEDONA_VERSION = "1.9.0"
EXPECTED_SPARK_SERIES = "3.5"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return "".join(ch for ch in text if ch.isalnum())


def peak_memory_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def load_rows(path: Path, *, kind: str) -> list[tuple[str, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[tuple[str, ...]] = []
    for feature in payload["features"]:
        props = feature["properties"]
        geometry_json = json.dumps(feature["geometry"], separators=(",", ":"))
        if kind == "municipios":
            rows.append((str(props["geoid"]), str(props["name"]), geometry_json))
        elif kind == "barrios":
            rows.append(
                (
                    str(props["geoid"]),
                    str(props["name"]),
                    str(props["municipio"]),
                    geometry_json,
                )
            )
        else:  # pragma: no cover - guarded by callers
            raise ValueError(kind)
    return rows


def build_context() -> Any:
    spark_series = ".".join(pyspark.__version__.split(".")[:2])
    if spark_series != EXPECTED_SPARK_SERIES:
        raise RuntimeError(
            f"Sedona reference is pinned to Spark {EXPECTED_SPARK_SERIES}.x; found {pyspark.__version__}"
        )
    packages = (
        f"org.apache.sedona:sedona-spark-{EXPECTED_SPARK_SERIES}_2.12:{SEDONA_VERSION},"
        f"org.datasyslab:geotools-wrapper:{SEDONA_VERSION}-33.5"
    )
    config = (
        SedonaContext.builder()
        .master("local[2]")
        .appName("aguayluz-spatial-shadow-reference")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.jars.packages", packages)
        .config(
            "spark.jars.repositories",
            "https://artifacts.unidata.ucar.edu/repository/unidata-all",
        )
        .getOrCreate()
    )
    return SedonaContext.create(config)


def close_enough(actual: float, expected: float, *, absolute: float, relative: float) -> bool:
    return math.isclose(actual, expected, abs_tol=absolute, rel_tol=relative)


def compare_receipts(local: dict[str, Any], sedona: dict[str, Any]) -> dict[str, Any]:
    tolerances = local["numeric_tolerances"]
    area_abs = float(tolerances["area_absolute_m2"])
    area_rel = float(tolerances["area_relative"])
    distance_abs = float(tolerances["distance_absolute_m"])

    failures: list[dict[str, Any]] = []
    max_deltas = {
        "barrio_area_m2": 0.0,
        "intersection_area_m2": 0.0,
        "outside_area_m2": 0.0,
        "coverage_ratio": 0.0,
        "centroid_to_municipio_boundary_m": 0.0,
    }

    for dataset in ("municipios", "barrios"):
        if local["inputs"][dataset]["sha256"] != sedona["inputs"][dataset]["sha256"]:
            failures.append({"type": "input_sha256", "dataset": dataset})
        if local["inputs"][dataset]["feature_count"] != sedona["inputs"][dataset]["feature_count"]:
            failures.append({"type": "input_feature_count", "dataset": dataset})

    local_rows = {row["barrio_geoid"]: row for row in local["records"]}
    sedona_rows = {row["barrio_geoid"]: row for row in sedona["records"]}
    if set(local_rows) != set(sedona_rows):
        failures.append(
            {
                "type": "record_key_set",
                "local_only": sorted(set(local_rows) - set(sedona_rows))[:20],
                "sedona_only": sorted(set(sedona_rows) - set(local_rows))[:20],
            }
        )

    exact_fields = (
        "municipio_geoid",
        "barrio_name",
        "municipio_name",
        "declared_parent_match",
        "topology_relation",
    )
    area_fields = ("barrio_area_m2", "intersection_area_m2", "outside_area_m2")

    for key in sorted(set(local_rows) & set(sedona_rows)):
        a = local_rows[key]
        b = sedona_rows[key]
        for field in exact_fields:
            if a[field] != b[field]:
                failures.append(
                    {"type": "exact_field", "barrio_geoid": key, "field": field, "local": a[field], "sedona": b[field]}
                )
        for field in area_fields:
            delta = abs(float(a[field]) - float(b[field]))
            max_deltas[field] = max(max_deltas[field], delta)
            if not close_enough(float(b[field]), float(a[field]), absolute=area_abs, relative=area_rel):
                failures.append(
                    {"type": "numeric_area", "barrio_geoid": key, "field": field, "local": a[field], "sedona": b[field], "delta": delta}
                )
        coverage_delta = abs(float(a["coverage_ratio"]) - float(b["coverage_ratio"]))
        max_deltas["coverage_ratio"] = max(max_deltas["coverage_ratio"], coverage_delta)
        if not close_enough(
            float(b["coverage_ratio"]),
            float(a["coverage_ratio"]),
            absolute=1e-10,
            relative=area_rel,
        ):
            failures.append(
                {"type": "numeric_ratio", "barrio_geoid": key, "field": "coverage_ratio", "local": a["coverage_ratio"], "sedona": b["coverage_ratio"], "delta": coverage_delta}
            )
        distance_field = "centroid_to_municipio_boundary_m"
        distance_delta = abs(float(a[distance_field]) - float(b[distance_field]))
        max_deltas[distance_field] = max(max_deltas[distance_field], distance_delta)
        if not close_enough(
            float(b[distance_field]),
            float(a[distance_field]),
            absolute=distance_abs,
            relative=0.0,
        ):
            failures.append(
                {"type": "numeric_distance", "barrio_geoid": key, "field": distance_field, "local": a[distance_field], "sedona": b[distance_field], "delta": distance_delta}
            )

    semantic_match = (
        local["operation"]["semantic_record_sha256"]
        == sedona["operation"]["semantic_record_sha256"]
    )
    if not semantic_match:
        failures.append({"type": "semantic_record_sha256"})

    return {
        "schema_version": "prii.spatial-compute-parity/v0.2",
        "status": "PASS" if not failures else "FAIL",
        "local_provider": local["provider"],
        "candidate_provider": sedona["provider"],
        "input_sha256_parity": all(
            local["inputs"][name]["sha256"] == sedona["inputs"][name]["sha256"]
            for name in ("municipios", "barrios")
        ),
        "semantic_record_parity": 1.0 if semantic_match else 0.0,
        "record_count_local": len(local_rows),
        "record_count_candidate": len(sedona_rows),
        "numeric_tolerances": tolerances,
        "max_absolute_deltas": max_deltas,
        "failure_count": len(failures),
        "failures": failures[:100],
        "canonical_write_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-receipt", required=True)
    parser.add_argument(
        "--output",
        default="reports/spatial_compute/sedona_reference_receipt.json",
    )
    parser.add_argument(
        "--parity-output",
        default="reports/spatial_compute/sedona_parity_receipt.json",
    )
    args = parser.parse_args()

    started = time.perf_counter()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    ref = config["reference_overlay"]
    municipios_path = ROOT / ref["left"]["path"]
    barrios_path = ROOT / ref["right"]["path"]

    municipio_rows = load_rows(municipios_path, kind="municipios")
    barrio_rows = load_rows(barrios_path, kind="barrios")
    if len(municipio_rows) != int(ref["left"]["expected_feature_count"]):
        raise RuntimeError(f"municipio feature count mismatch: {len(municipio_rows)}")
    if len(barrio_rows) != int(ref["right"]["expected_feature_count"]):
        raise RuntimeError(f"barrio feature count mismatch: {len(barrio_rows)}")

    sedona = build_context()
    try:
        municipios_raw = sedona.createDataFrame(
            municipio_rows,
            ["municipio_geoid", "municipio_name", "geometry_json"],
        )
        barrios_raw = sedona.createDataFrame(
            barrio_rows,
            ["barrio_geoid", "barrio_name", "declared_municipio", "geometry_json"],
        )
        municipios = municipios_raw.selectExpr(
            "municipio_geoid",
            "municipio_name",
            "ST_GeomFromGeoJSON(geometry_json) AS geometry",
        )
        barrios = barrios_raw.selectExpr(
            "barrio_geoid",
            "barrio_name",
            "declared_municipio",
            "ST_GeomFromGeoJSON(geometry_json) AS geometry",
        )
        municipios.createOrReplaceTempView("shadow_municipios")
        barrios.createOrReplaceTempView("shadow_barrios")

        metric_crs = ref["computation_crs"]
        query = f"""
        WITH matched AS (
          SELECT
            b.barrio_geoid,
            b.barrio_name,
            b.declared_municipio,
            m.municipio_geoid,
            m.municipio_name,
            ST_Transform(b.geometry, 'EPSG:4326', '{metric_crs}') AS barrio_metric,
            ST_Transform(m.geometry, 'EPSG:4326', '{metric_crs}') AS municipio_metric
          FROM shadow_barrios b
          JOIN shadow_municipios m
            ON ST_Within(ST_PointOnSurface(b.geometry), m.geometry)
        ), metrics AS (
          SELECT
            barrio_geoid,
            barrio_name,
            declared_municipio,
            municipio_geoid,
            municipio_name,
            CASE
              WHEN ST_Within(barrio_metric, municipio_metric) THEN 'FULL_WITHIN'
              WHEN ST_Intersects(barrio_metric, municipio_metric) THEN 'INTERSECTS'
              ELSE 'DISJOINT'
            END AS topology_relation,
            ST_Area(barrio_metric) AS barrio_area_m2,
            ST_Area(ST_Intersection(barrio_metric, municipio_metric)) AS intersection_area_m2,
            ST_Distance(ST_Centroid(barrio_metric), ST_Boundary(municipio_metric))
              AS centroid_to_municipio_boundary_m
          FROM matched
        )
        SELECT
          barrio_geoid,
          barrio_name,
          declared_municipio,
          municipio_geoid,
          municipio_name,
          topology_relation,
          barrio_area_m2,
          intersection_area_m2,
          GREATEST(0.0, barrio_area_m2 - intersection_area_m2) AS outside_area_m2,
          CASE WHEN barrio_area_m2 = 0 THEN 0.0 ELSE intersection_area_m2 / barrio_area_m2 END
            AS coverage_ratio,
          centroid_to_municipio_boundary_m
        FROM metrics
        ORDER BY barrio_geoid
        """
        collected = sedona.sql(query).collect()
    finally:
        sedona.stop()

    if len(collected) != int(ref["expected_record_count"]):
        raise RuntimeError(f"Sedona expected {ref['expected_record_count']} records, found {len(collected)}")

    counts: dict[str, int] = {}
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in collected:
        barrio_geoid = str(row["barrio_geoid"])
        if barrio_geoid in seen:
            raise RuntimeError(f"duplicate Sedona barrio parent result: {barrio_geoid}")
        seen.add(barrio_geoid)
        parent_match = norm_name(row["declared_municipio"]) == norm_name(row["municipio_name"])
        if not parent_match:
            raise RuntimeError(
                f"Sedona parent mismatch {barrio_geoid}: {row['declared_municipio']} != {row['municipio_name']}"
            )
        topology = str(row["topology_relation"])
        counts[topology] = counts.get(topology, 0) + 1
        records.append(
            {
                "barrio_geoid": barrio_geoid,
                "municipio_geoid": str(row["municipio_geoid"]),
                "barrio_name": str(row["barrio_name"]),
                "municipio_name": str(row["municipio_name"]),
                "declared_parent_match": parent_match,
                "topology_relation": topology,
                "barrio_area_m2": round(float(row["barrio_area_m2"]), 6),
                "intersection_area_m2": round(float(row["intersection_area_m2"]), 6),
                "outside_area_m2": round(float(row["outside_area_m2"]), 6),
                "coverage_ratio": round(float(row["coverage_ratio"]), 12),
                "centroid_to_municipio_boundary_m": round(
                    float(row["centroid_to_municipio_boundary_m"]), 6
                ),
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

    local = json.loads(Path(args.local_receipt).read_text(encoding="utf-8"))
    receipt = {
        "schema_version": "prii.spatial-compute-reference-receipt/v0.2",
        "status": "PASS",
        "provider": {
            "provider_name": "local_apache_sedona_spark",
            "provider_version": SEDONA_VERSION,
            "spark_version": pyspark.__version__,
            "canonical_write_authority": False,
            "monetary_cost_usd": 0.0,
        },
        "contract": str(CONFIG_PATH.relative_to(ROOT)),
        "pixel_grid_used": False,
        "inputs": {
            "municipios": {
                "path": str(municipios_path.relative_to(ROOT)),
                "bytes": municipios_path.stat().st_size,
                "sha256": sha256_file(municipios_path),
                "feature_count": len(municipio_rows),
            },
            "barrios": {
                "path": str(barrios_path.relative_to(ROOT)),
                "bytes": barrios_path.stat().st_size,
                "sha256": sha256_file(barrios_path),
                "feature_count": len(barrio_rows),
            },
        },
        "operation": {
            "parent_join": ref["join_semantics"],
            "metric_geometry": ref["metric_geometry"],
            "distance_metric": ref["distance_metric"],
            "computation_crs": metric_crs,
            "record_count": len(records),
            "declared_parent_match_count": sum(r["declared_parent_match"] for r in records),
            "topology_counts": counts,
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

    parity = compare_receipts(local, receipt)
    parity_output = Path(args.parity_output)
    if not parity_output.is_absolute():
        parity_output = ROOT / parity_output
    parity_output.parent.mkdir(parents=True, exist_ok=True)
    parity_output.write_text(json.dumps(parity, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "sedona_status": receipt["status"],
                "parity_status": parity["status"],
                "records": len(records),
                "semantic_record_sha256": receipt["operation"]["semantic_record_sha256"],
                "topology_counts": counts,
                "max_absolute_deltas": parity["max_absolute_deltas"],
                "failure_count": parity["failure_count"],
                "runtime_ms": receipt["runtime"]["runtime_ms"],
            },
            sort_keys=True,
        )
    )
    if parity["status"] != "PASS":
        raise SystemExit("Apache Sedona parity gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
