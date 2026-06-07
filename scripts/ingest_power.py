#!/usr/bin/env python3
"""Ingest real PR power infrastructure into aguayluz utility_assets.jsonl.

Source: the curated ``Spiderweb_Power_Infrastructure_Layer.geojson`` (PR generation,
substation, and transmission-corridor nodes with municipality / operator / coords /
confidence, built from public EIA + OSM data). Produces schema-valid rows for
``schemas/utility_asset.schema.json`` (additionalProperties=false), which
``scripts/federation_export.py`` then projects into the federation canonical streams.

The source data lives outside the repo (machine-local); pass ``--src`` to override.
The materialized ``data/utility_assets.jsonl`` IS committed (small, public-derived).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_SRC = "/Users/jotaele/Documents/Data/Energy_Sector/Geospatial/GeoJSON/Spiderweb_Power_Infrastructure_Layer.geojson"


def _tier(conf: float) -> str:
    return "T1" if conf >= 90 else "T2" if conf >= 75 else "T3" if conf >= 50 else "T4"


def _subtype(props: dict) -> str:
    sub = props.get("subcategory") or props.get("type") or "unknown"
    fuel = props.get("fuel_type")
    if fuel and str(fuel).lower() not in ("none", "n/a", ""):
        return f"{sub} ({fuel})"
    return sub


def build_assets(features: list) -> list:
    rows = []
    for f in features:
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        coords = g.get("coordinates")
        lat = lon = None
        if g.get("type") == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lon, lat = float(coords[0]), float(coords[1])
        conf = p.get("confidence") or 0
        if conf <= 1:
            conf = round(conf * 100)
        conf = int(conf)
        row = {
            "asset_id": p.get("power_node_id") or f"PWR_{p.get('id')}",
            "asset_name": p.get("name") or p.get("power_node_id") or "unknown power asset",
            "asset_type": "power",
            "asset_subtype": _subtype(p),
            "municipality": p.get("municipality") or "unknown",
            "geometry_type": "point" if lat is not None else "unknown",
            "status": "active",
            "source_ref": p.get("source") or "Spiderweb_Power_Infrastructure_Layer",
            "evidence_tier": _tier(conf),
            "confidence": conf,
            "review_status": "accepted",
        }
        if p.get("operator"):
            row["operator"] = p["operator"]
        if lat is not None:
            row["lat"] = lat
            row["lon"] = lon
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default="data/utility_assets.jsonl")
    args = ap.parse_args()

    doc = json.loads(Path(args.src).read_text())
    rows = build_assets(doc.get("features", []))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"wrote {len(rows)} utility assets -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
