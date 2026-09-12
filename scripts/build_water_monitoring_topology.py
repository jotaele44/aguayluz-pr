#!/usr/bin/env python3
"""Build one-row-per-station watershed topology from frozen GeoJSON inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

FINAL_STATES = {
    "FULLY_WITHIN",
    "PARTIAL",
    "TOUCH_ONLY",
    "OUTSIDE",
    "NULL_EMPTY",
    "UNRESOLVED",
}


def _stable_watershed_id(properties: dict[str, Any]) -> str | None:
    for key in ("GlobalID", "CUENCA_ID"):
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def classify_point(point: Any, polygons: list[tuple[str, Any]]) -> dict[str, Any]:
    if point is None or point.is_empty:
        return {"spatial_state": "NULL_EMPTY", "candidate_watershed_ids": []}

    within = [watershed_id for watershed_id, geom in polygons if point.within(geom)]
    touches = [watershed_id for watershed_id, geom in polygons if point.touches(geom)]
    if len(within) == 1:
        return {
            "spatial_state": "FULLY_WITHIN",
            "candidate_watershed_ids": within,
            "watershed_id": within[0],
        }
    if len(within) > 1:
        return {"spatial_state": "UNRESOLVED", "candidate_watershed_ids": within}
    if touches:
        return {"spatial_state": "TOUCH_ONLY", "candidate_watershed_ids": touches}
    return {"spatial_state": "OUTSIDE", "candidate_watershed_ids": []}


def build_topology(stations_path: Path, watersheds_path: Path) -> list[dict[str, Any]]:
    import geopandas as gpd

    stations = gpd.read_file(stations_path)
    watersheds = gpd.read_file(watersheds_path)
    if stations.crs is None or watersheds.crs is None:
        raise RuntimeError("Both inputs require declared CRS")
    if not all(geom is None or geom.geom_type == "Point" for geom in stations.geometry):
        raise RuntimeError("Station input must contain only Point/null geometry")
    if not all(
        geom is None or geom.geom_type in {"Polygon", "MultiPolygon"}
        for geom in watersheds.geometry
    ):
        raise RuntimeError("Watershed input must contain only Polygon/MultiPolygon/null geometry")

    watersheds = watersheds.to_crs(stations.crs)
    polygon_rows: list[tuple[str, Any]] = []
    stable_ids: list[str] = []
    for _, row in watersheds.iterrows():
        props = row.drop(labels=[watersheds.geometry.name]).to_dict()
        stable_id = _stable_watershed_id(props)
        if stable_id is None:
            raise RuntimeError("Watershed lacks GlobalID/CUENCA_ID stable identifier")
        stable_ids.append(stable_id)
        if row.geometry is not None and not row.geometry.is_empty:
            polygon_rows.append((stable_id, row.geometry))
    if len(set(stable_ids)) != len(stable_ids):
        raise RuntimeError("Watershed stable identifiers are not unique")

    output: list[dict[str, Any]] = []
    seen_station_ids: set[str] = set()
    for _, row in stations.iterrows():
        station_id = row.get("asset_id") or row.get("site_no") or row.get("id")
        if station_id in (None, ""):
            raise RuntimeError("Station lacks asset_id/site_no/id")
        station_id = str(station_id)
        if station_id in seen_station_ids:
            raise RuntimeError(f"Duplicate station identifier: {station_id}")
        seen_station_ids.add(station_id)
        result = classify_point(row.geometry, polygon_rows)
        if result["spatial_state"] not in FINAL_STATES:
            raise RuntimeError("Unexpected spatial state")
        output.append({"station_id": station_id, **result})

    if len(output) != len(stations):
        raise RuntimeError("Row-conservation failure")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stations", type=Path, required=True)
    parser.add_argument("--watersheds", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = build_topology(args.stations, args.watersheds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {state: sum(row["spatial_state"] == state for row in rows) for state in FINAL_STATES}
    print(json.dumps({"rows": len(rows), "states": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
