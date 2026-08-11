#!/usr/bin/env python3
"""Ingest OSM power infrastructure (substations, plants, lines) into utility_assets.

Expands the power asset layer beyond the curated 39-node Spiderweb set that
`ingest_power.py` loads. Source: the OpenStreetMap power extracts in the
Energy_Sector corpus —
  power_plant.geojson              generation sites (source=solar/wind/…, output kW)
  power_substation_point.geojson   substations (point)
  power_substation_polygon.geojson substations (footprint → centroid)
  power_line.geojson               transmission/distribution lines

NOTE — this is the OSM layer, NOT HIFLD. The authoritative HIFLD substation/line
GIS (`hifld_pr_pull.py`) targets an ArcGIS REST host the sandbox can't reach; run
that pull locally to add the T1 layer, then dedupe against these OSM rows by
proximity. OSM here is unverified community data, so rows are T3/needs_review
(matching the OSM water layer in `ingest_water.py`).

asset_id prefixes keep layers from colliding: OSMP_ (plant), OSMS_ (substation),
OSML_ (line). MERGE preserves every non-OSM* row and replaces OSM* rows, so run
AFTER `ingest_power.py` (which OVERWRITES the file) — e.g.:
    python scripts/ingest_power.py
    python scripts/ingest_osm_power.py
    python scripts/ingest_water.py ; python scripts/ingest_usgs_water.py ; …

Reads the machine-local corpus; pass --src-dir to override.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_SRC_DIR = "/Users/jotaele/Documents/Data/Energy_Sector/Geospatial/GeoJSON"
LAT_MIN, LAT_MAX = 17.7, 18.7
LON_MIN, LON_MAX = -67.95, -65.2
REPO = Path(__file__).resolve().parent.parent
MUNI_GEOJSON = REPO / "data" / "geo" / "pr_municipios.geojson"

# file stem -> (asset_subtype builder key, id_prefix, geometry_type, label)
LAYERS = {
    "power_plant":              ("generation", "OSMP", "point", "Power Plant"),
    "power_substation_point":   ("substation", "OSMS", "point", "Substation"),
    "power_substation_polygon": ("substation", "OSMS", "point", "Substation"),
    "power_line":               ("transmission_line", "OSML", "line", "Power Line"),
}


# ── geometry → representative (lat, lon) in PR bounds ──────────────────────────
def _ring_centroid(ring: list) -> tuple[float, float] | None:
    pts = [c for c in ring if isinstance(c, (list, tuple)) and len(c) >= 2]
    if not pts:
        return None
    lon = sum(float(c[0]) for c in pts) / len(pts)
    lat = sum(float(c[1]) for c in pts) / len(pts)
    return lat, lon


def representative_point(geom: dict[str, Any]) -> tuple[float, float] | None:
    t = geom.get("type")
    c = geom.get("coordinates")
    if not c:
        return None
    try:
        if t == "Point":
            return float(c[1]), float(c[0])
        if t == "Polygon":
            return _ring_centroid(c[0])
        if t == "MultiPolygon":
            return _ring_centroid(c[0][0])
        if t == "LineString":
            mid = c[len(c) // 2]
            return float(mid[1]), float(mid[0])
        if t == "MultiLineString":
            line = c[0]
            mid = line[len(line) // 2]
            return float(mid[1]), float(mid[0])
    except (TypeError, ValueError, IndexError):
        return None
    return None


# ── municipality by point-in-polygon ──────────────────────────────────────────
def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def load_municipios(path: Path) -> list[tuple[str, list]]:
    if not path.is_file():
        return []
    doc = json.loads(path.read_text())
    out = []
    for feat in doc.get("features", []):
        name = (feat.get("properties") or {}).get("name")
        g = feat.get("geometry") or {}
        if not name:
            continue
        if g.get("type") == "Polygon" and g.get("coordinates"):
            out.append((name, [g["coordinates"][0]]))
        elif g.get("type") == "MultiPolygon":
            out.append((name, [p[0] for p in g["coordinates"] if p]))
    return out


def municipality_for(lat: float, lon: float, munis: list[tuple[str, list]]) -> str:
    for name, rings in munis:
        for ring in rings:
            if _point_in_ring(lon, lat, ring):
                return name
    return "unknown"


# ── subtype ───────────────────────────────────────────────────────────────────
def plant_subtype(props: dict) -> str:
    src = props.get("source") or props.get("method") or "unknown"
    return f"generation ({src})"


# ── build rows ────────────────────────────────────────────────────────────────
def build_rows(src_dir: Path, munis: list[tuple[str, list]]) -> list[dict]:
    try:
        sys.path.insert(0, str(REPO / "src"))
        from aguayluz.confidence import score
    except Exception:
        def score(tier, has_coords=True, **_):
            return {"T1": 80, "T2": 60, "T3": 45, "T4": 30}[tier] - (0 if has_coords else 15)

    rows: list[dict] = []
    seen: set[str] = set()
    for stem, (subkind, prefix, geom_type, label) in LAYERS.items():
        path = src_dir / f"{stem}.geojson"
        if not path.is_file():
            continue
        doc = json.loads(path.read_text())
        for f in doc.get("features", []):
            p = f.get("properties") or {}
            fid = p.get("id")
            if fid is None:
                continue
            asset_id = f"{prefix}_{fid}"
            if asset_id in seen:
                continue
            seen.add(asset_id)
            subtype = plant_subtype(p) if subkind == "generation" else subkind
            rp = representative_point(f.get("geometry") or {})
            lat = lon = None
            if rp and LAT_MIN <= rp[0] <= LAT_MAX and LON_MIN <= rp[1] <= LON_MAX:
                lat, lon = round(rp[0], 6), round(rp[1], 6)
            muni = municipality_for(lat, lon, munis) if (lat is not None and munis) else "unknown"
            name = p.get("name") or p.get("name_en") or p.get("ref")
            row = {
                "asset_id": asset_id,
                "asset_name": name or f"{label} {fid}",
                "asset_type": "power",
                "asset_subtype": subtype,
                "municipality": muni,
                "geometry_type": geom_type if lat is not None else "unknown",
                "status": "construction" if p.get("construction") else "active",
                "source_ref": f"OpenStreetMap {stem} (PR extract)",
                "evidence_tier": "T3",
                "confidence": int(score("T3", has_coords=lat is not None)),
                "review_status": "needs_review",
            }
            op = p.get("operator") or p.get("wd_operator")
            if op:
                row["operator"] = op
            if lat is not None:
                row["lat"], row["lon"] = lat, lon
            rows.append(row)
    return rows


# ── merge + write ─────────────────────────────────────────────────────────────
OSM_PREFIXES = ("OSMP_", "OSMS_", "OSML_")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], osm: list[dict]) -> list[dict]:
    by_id = {r["asset_id"]: r for r in existing
             if not str(r.get("asset_id", "")).startswith(OSM_PREFIXES)}
    for r in osm:
        by_id[r["asset_id"]] = r
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src-dir", default=DEFAULT_SRC_DIR)
    ap.add_argument("--out", default="data/utility_assets.jsonl")
    ap.add_argument("--muni-geojson", default=str(MUNI_GEOJSON))
    args = ap.parse_args()

    src_dir = Path(args.src_dir)
    if not src_dir.is_dir():
        print(f"OSM power source dir absent ({src_dir}); skipping")
        return 0
    munis = load_municipios(Path(args.muni_geojson))
    rows = build_rows(src_dir, munis)
    if not rows:
        print(f"no OSM power features found under {src_dir}; skipping")
        return 0

    out = Path(args.out)
    combined = merge(_read_jsonl(out), rows)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))

    sub: dict[str, int] = {}
    for r in rows:
        key = "generation" if r["asset_subtype"].startswith("generation") else r["asset_subtype"]
        sub[key] = sub.get(key, 0) + 1
    located = sum(1 for r in rows if "lat" in r)
    print(f"wrote {len(rows)} OSM power assets ({located} geolocated) -> {out}")
    print(f"  by subtype: {sub}")
    print(f"  total assets in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
