#!/usr/bin/env python3
"""Ingest HIFLD power infrastructure (T1) into aguayluz utility_assets.jsonl.

The authoritative federal GIS layer for PR power infrastructure, pulled by
``Energy_Sector/Scripts/hifld_pr_pull.py`` (endpoints fixed + verified 2026-06) into:
  hifld_pr_power_plants.geojson         48 plants  (Point; fuel, capacity, operator)
  hifld_pr_substations.geojson         498 subs    (Point; voltage) ← biggest gap fill
  hifld_pr_transmission_lines.geojson  141 lines   (LineString; owner, voltage class)

Maps each → schema-valid ``utility_asset`` (asset_type=power, T1/accepted):
  plants       subtype = "generation (<PRIM_FUEL>)"   id HIFLD_PP_<plant_code>
  substations  subtype = "substation (<MAX_VOLT>kV)"  id HIFLD_SS_<id>
  lines        subtype = "transmission_line (<VOLT_CLASS>)" id HIFLD_TL_<id>, geom=line

This is the **T1** layer; the OSM layer (OSMP_/OSMS_/OSML_) and the coordless EIA
plants (EIA_PLANT_*) remain alongside it. True cross-source dedup (HIFLD plant ↔
EIA plant by PLANT_CODE; HIFLD ↔ OSM substation by proximity) is a follow-on
enrichment — see remaining_work_queue.md. Municipality resolved by point-in-polygon
against data/geo/pr_municipios.geojson (lines use their midpoint).

Run AFTER ingest_power.py (which OVERWRITES utility_assets.jsonl); merge preserves
every non-HIFLD row and replaces HIFLD_* rows:
    python scripts/ingest_hifld_power.py
    python scripts/ingest_hifld_power.py --src-dir /path/to/GeoJSON   # override
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

# stem -> (id_prefix, kind, geometry_type)
LAYERS = {
    "hifld_pr_power_plants":       ("HIFLD_PP", "plant", "point"),
    "hifld_pr_substations":       ("HIFLD_SS", "substation", "point"),
    "hifld_pr_transmission_lines": ("HIFLD_TL", "line", "line"),
}
HIFLD_PREFIXES = ("HIFLD_PP_", "HIFLD_SS_", "HIFLD_TL_")


# ── geometry → representative (lat, lon) ──────────────────────────────────────
def _ring_centroid(ring: list) -> tuple[float, float] | None:
    pts = [c for c in ring if isinstance(c, (list, tuple)) and len(c) >= 2]
    if not pts:
        return None
    return (sum(float(c[1]) for c in pts) / len(pts),
            sum(float(c[0]) for c in pts) / len(pts))


def representative_point(geom: dict[str, Any]) -> tuple[float, float] | None:
    t, c = geom.get("type"), geom.get("coordinates")
    if not c:
        return None
    try:
        if t == "Point":
            return float(c[1]), float(c[0])
        if t == "MultiPoint":
            return float(c[0][1]), float(c[0][0])
        if t == "LineString":
            m = c[len(c) // 2]
            return float(m[1]), float(m[0])
        if t == "MultiLineString":
            line = c[0]
            m = line[len(line) // 2]
            return float(m[1]), float(m[0])
        if t == "Polygon":
            return _ring_centroid(c[0])
        if t == "MultiPolygon":
            return _ring_centroid(c[0][0])
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


# ── field helpers ─────────────────────────────────────────────────────────────
def _status(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    if not s or s in ("NOT AVAILABLE", "NA", "N/A"):
        return "unknown"
    if "RETIR" in s or "INACTIVE" in s:
        return "inactive"
    if "CONST" in s or "PLAN" in s or "PROPOSED" in s:
        return "planned"
    if "SERVICE" in s or "OPERAT" in s or s == "TRUE":
        return "active"
    return "active"


def _fmt_volt(v: Any) -> str | None:
    try:
        f = float(v)
        if f <= 0:
            return None
        return f"{f:g}kV"
    except (TypeError, ValueError):
        return None


def _subtype(kind: str, p: dict) -> str:
    if kind == "plant":
        fuel = (p.get("PRIM_FUEL") or p.get("TYPE") or "unknown")
        return f"generation ({str(fuel).strip() or 'unknown'})"
    if kind == "substation":
        v = _fmt_volt(p.get("MAX_VOLT"))
        return f"substation ({v})" if v else "substation"
    v = p.get("VOLT_CLASS") or _fmt_volt(p.get("VOLTAGE"))
    return f"transmission_line ({str(v).strip()})" if v and str(v).strip() not in ("NOT AVAILABLE",) else "transmission_line"


def _feature_id(p: dict, prefix: str) -> str | None:
    raw = p.get("PLANT_CODE") or p.get("ID") or p.get("OBJECTID") or p.get("OBJECTID_1")
    if raw in (None, "", "NOT AVAILABLE"):
        raw = p.get("OBJECTID_1")
    return f"{prefix}_{raw}" if raw not in (None, "") else None


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
    for stem, (prefix, kind, geom_type) in LAYERS.items():
        path = src_dir / f"{stem}.geojson"
        if not path.is_file():
            continue
        doc = json.loads(path.read_text())
        for f in doc.get("features", []):
            p = f.get("properties") or {}
            asset_id = _feature_id(p, prefix)
            if not asset_id or asset_id in seen:
                continue
            seen.add(asset_id)
            # coords: prefer LATITUDE/LONGITUDE attrs (points), else geometry
            lat = lon = None
            la, lo = p.get("LATITUDE"), p.get("LONGITUDE")
            try:
                if la not in (None, "") and lo not in (None, ""):
                    la, lo = float(la), float(lo)
                    if LAT_MIN <= la <= LAT_MAX and LON_MIN <= lo <= LON_MAX:
                        lat, lon = round(la, 6), round(lo, 6)
            except (TypeError, ValueError):
                # Malformed attributes are non-authoritative; geometry below is
                # the only permitted fallback and is independently bounds-checked.
                pass
            if lat is None:
                rp = representative_point(f.get("geometry") or {})
                if rp and LAT_MIN <= rp[0] <= LAT_MAX and LON_MIN <= rp[1] <= LON_MAX:
                    lat, lon = round(rp[0], 6), round(rp[1], 6)
            muni = municipality_for(lat, lon, munis) if (lat is not None and munis) else "unknown"
            name = (p.get("NAME") or "").strip()
            label = {"plant": "Power Plant", "substation": "Substation",
                     "line": "Transmission Line"}[kind]
            row = {
                "asset_id": asset_id,
                "asset_name": name or f"{label} {asset_id.split('_')[-1]}",
                "asset_type": "power",
                "asset_subtype": _subtype(kind, p),
                "municipality": muni,
                "geometry_type": geom_type if lat is not None else "unknown",
                "status": _status(p.get("STATUS")),
                "source_ref": f"HIFLD {stem.replace('hifld_pr_', '').replace('_', ' ')} (ArcGIS REST)",
                "evidence_tier": "T1",
                "confidence": int(score("T1", has_coords=lat is not None)),
                "review_status": "accepted",
            }
            op = p.get("OPERATOR") or p.get("OWNER")
            if op and str(op).strip() and str(op).strip() != "NOT AVAILABLE":
                row["operator"] = str(op).strip()
            if lat is not None:
                row["lat"], row["lon"] = lat, lon
            rows.append(row)
    return rows


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], hifld: list[dict]) -> list[dict]:
    by_id = {r["asset_id"]: r for r in existing
             if not str(r.get("asset_id", "")).startswith(HIFLD_PREFIXES)}
    for r in hifld:
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
        print(f"HIFLD source dir absent ({src_dir}); run hifld_pr_pull.py first. Skipping.")
        return 0
    munis = load_municipios(Path(args.muni_geojson))
    rows = build_rows(src_dir, munis)
    if not rows:
        print(f"no HIFLD features under {src_dir} (run hifld_pr_pull.py). Skipping.")
        return 0

    out = Path(args.out)
    combined = merge(_read_jsonl(out), rows)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))

    sub: dict[str, int] = {}
    for r in rows:
        k = ("generation" if r["asset_subtype"].startswith("generation")
             else "substation" if r["asset_subtype"].startswith("substation")
             else "transmission_line")
        sub[k] = sub.get(k, 0) + 1
    located = sum(1 for r in rows if "lat" in r)
    print(f"wrote {len(rows)} HIFLD power assets ({located} geolocated) -> {out}")
    print(f"  by subtype: {sub}")
    print(f"  total assets in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
