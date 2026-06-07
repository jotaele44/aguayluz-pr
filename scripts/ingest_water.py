#!/usr/bin/env python3
"""Ingest real PR water / wastewater infrastructure into aguayluz utility_assets.jsonl.

Complements ``ingest_power.py`` (which loads the curated power layer). Sources are
the public PR_Geodata OSM-derived layers — water treatment plants, wastewater
plants, pumping stations, and reservoirs — as polygon footprints. Each feature
becomes a schema-valid ``utility_asset`` row (representative point = polygon
centroid) that ``scripts/federation_export.py`` projects into the federation
canonical streams (carrying the centroid as the entity ``location``, Z2).

OSM attributes are sparse (name/operator often null) and unverified, so rows are
emitted with ``review_status=needs_review`` / ``evidence_tier=T3``.

This MERGES into ``data/utility_assets.jsonl``: existing non-water rows (e.g. the
power assets from ingest_power) are preserved; water/wastewater rows are replaced.
Run ``ingest_power`` first, then ``ingest_water``. Source data is machine-local
(``--src-dir`` to override); the materialized JSONL is committed (small, public).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_SRC_DIR = "/Users/jotaele/Documents/Data/PR_Geodata/06_Vector_GeoJSON"

# layer file stem -> (asset_type, asset_subtype, id_prefix, display label)
LAYERS = {
    "water_treatment_plant": ("water", "treatment", "WTR", "Water Treatment Plant"),
    "wastewater_plant": ("wastewater", "wastewater_treatment", "WWT", "Wastewater Plant"),
    "pumping_station": ("water", "pumping_station", "PMP", "Pumping Station"),
    "water_reservoir": ("water", "reservoir", "RSV", "Reservoir"),
}
WATER_TYPES = {"water", "wastewater"}


def _centroid(geom: dict[str, Any]) -> tuple[float, float] | None:
    """Representative (lat, lon) for a feature: polygon-ring centroid or a point."""
    t = geom.get("type")
    coords = geom.get("coordinates")
    ring = None
    if t == "Polygon" and coords:
        ring = coords[0]
    elif t == "MultiPolygon" and coords and coords[0]:
        ring = coords[0][0]
    elif t == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        return float(coords[1]), float(coords[0])
    if not ring:
        return None
    pts = [c for c in ring if isinstance(c, (list, tuple)) and len(c) >= 2]
    if not pts:
        return None
    lon = sum(float(c[0]) for c in pts) / len(pts)
    lat = sum(float(c[1]) for c in pts) / len(pts)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return round(lat, 6), round(lon, 6)


def build_water_assets(src_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stem, (atype, subtype, prefix, label) in LAYERS.items():
        path = src_dir / f"{stem}.geojson"
        if not path.is_file():
            continue
        doc = json.loads(path.read_text())
        for f in doc.get("features", []):
            p = f.get("properties") or {}
            pt = _centroid(f.get("geometry") or {})
            fid = p.get("id")
            name = p.get("name") or p.get("name_en") or p.get("ref")
            row: dict[str, Any] = {
                "asset_id": f"{prefix}_{fid}",
                "asset_name": name or f"{label} {fid}",
                "asset_type": atype,
                "asset_subtype": subtype,
                "municipality": "unknown",
                "geometry_type": "polygon",
                "status": "active",
                "source_ref": f"PR_Geodata/{stem}.geojson (OSM)",
                "evidence_tier": "T3",
                "confidence": 60,
                "review_status": "needs_review",
            }
            op = p.get("operator") or p.get("wd_operator")
            if op:
                row["operator"] = op
            if pt is not None:
                row["lat"], row["lon"] = pt
            rows.append(row)
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def merge(existing: list[dict[str, Any]], water: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep existing non-water rows; append water rows; dedup by asset_id (water wins)."""
    kept = [r for r in existing if r.get("asset_type") not in WATER_TYPES]
    by_id: dict[str, dict[str, Any]] = {r["asset_id"]: r for r in kept}
    for r in water:
        by_id[r["asset_id"]] = r
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src-dir", default=DEFAULT_SRC_DIR)
    ap.add_argument("--out", default="data/utility_assets.jsonl")
    args = ap.parse_args()

    water = build_water_assets(Path(args.src_dir))
    out = Path(args.out)
    combined = merge(_read_jsonl(out), water)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))
    print(f"wrote {len(water)} water/wastewater assets ({len(combined)} total) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
