#!/usr/bin/env python3
"""Cross-source power-asset dedup → data/asset_crosswalk.jsonl (non-destructive).

The power layer now holds the same real-world facilities from up to four sources
(HIFLD T1, EIA facility-fuel T1, Spiderweb curated, OSM T3). This builds a
CROSSWALK: clusters of utility_asset ids that are the same facility, with a
best-evidence canonical — WITHOUT deleting anything from utility_assets.jsonl
(the ingests are idempotent + re-run weekly, so a destructive merge would just be
re-added; and provenance must be preserved).

Identity rule (cross-source only — never merges two rows from the same source):
  * plant_code  — HIFLD_PP_<code> ↔ EIA_PLANT_<code> share an EIA plant code.
                  (Also lends the coordless EIA plant its HIFLD twin's geometry.)
Proximity is corroboration/discovery only. It can annotate an exact plant-code
cluster, but it never creates identity by itself.
Clusters via union-find; canonical = min(evidence_tier, then has-coords, then
source rank HIFLD>EIA>Spiderweb>OSM). Output validated against
schemas/asset_crosswalk.schema.json.

Run after the power ingests (ingest_power / osm / facility_fuel / hifld):
    python scripts/dedup_power_assets.py
    python scripts/dedup_power_assets.py --plant-m 800 --sub-m 400
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE_PREFIXES = [
    ("HIFLD_PP_", "HIFLD"), ("HIFLD_SS_", "HIFLD"), ("HIFLD_TL_", "HIFLD"),
    ("EIA_PLANT_", "EIA"), ("EIA_UTIL_", "EIA"),
    ("PWR", "Spiderweb"),
    ("OSMP_", "OSM"), ("OSMS_", "OSM"), ("OSML_", "OSM"),
]
SOURCE_RANK = {"HIFLD": 0, "EIA": 1, "Spiderweb": 2, "OSM": 3, "other": 4}
TIER_RANK = {"T1": 0, "T2": 1, "T3": 2, "T4": 3}


def source_of(asset_id: str) -> str:
    for pfx, src in SOURCE_PREFIXES:
        if asset_id.startswith(pfx):
            return src
    return "other"


def asset_class(r: dict) -> str:
    s = (r.get("asset_subtype") or "").lower()
    if s.startswith("generation"):
        return "generation"
    if s.startswith("substation"):
        return "substation"
    if s.startswith("transmission"):
        return "transmission_line"
    return "other"


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


class UF:
    def __init__(self):
        self.p: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _coords(r: dict):
    if isinstance(r.get("lat"), (int, float)) and isinstance(r.get("lon"), (int, float)):
        lat, lon = float(r["lat"]), float(r["lon"])
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            return (lat, lon)
    return None


def build_clusters(power: list[dict], plant_m: float, sub_m: float):
    by_id: dict[str, dict] = {}
    for row in power:
        asset_id = row["asset_id"]
        if asset_id in by_id:
            raise ValueError(f"duplicate asset_id: {asset_id}")
        by_id[asset_id] = row
    uf = UF()
    edges: dict[frozenset, str] = {}  # (a,b) -> method

    # 1) plant_code exact: HIFLD_PP_<code> <-> EIA_PLANT_<code>
    hifld_pp = {r["asset_id"].removeprefix("HIFLD_PP_"): r["asset_id"]
                for r in power if r["asset_id"].startswith("HIFLD_PP_")}
    for r in power:
        if r["asset_id"].startswith("EIA_PLANT_"):
            code = r["asset_id"].removeprefix("EIA_PLANT_")
            if code in hifld_pp:
                uf.union(r["asset_id"], hifld_pp[code])
                edges[frozenset((r["asset_id"], hifld_pp[code]))] = "plant_code"

    # 2) proximity is discovery/corroboration only. Never union on distance.
    geo = [(r["asset_id"], asset_class(r), source_of(r["asset_id"]), _coords(r))
           for r in power]
    geo = [g for g in geo if g[3] is not None and g[1] in ("generation", "substation")]
    thr = {"generation": plant_m, "substation": sub_m}
    for i in range(len(geo)):
        idi, ci, si, pi = geo[i]
        for j in range(i + 1, len(geo)):
            idj, cj, sj, pj = geo[j]
            if ci != cj or si == sj:
                continue
            d = haversine_m(pi, pj)
            if d <= thr[ci]:
                key = frozenset((idi, idj))
                if key in edges:
                    edges[key] = "plant_code+proximity"

    # gather clusters
    clusters: dict[str, list[str]] = {}
    for aid in list(uf.p):
        clusters.setdefault(uf.find(aid), []).append(aid)

    out = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        recs = [by_id[m] for m in members]
        # canonical: best tier, prefer coords, then source rank
        def rank(r):
            return (TIER_RANK.get(r.get("evidence_tier"), 9),
                    0 if _coords(r) else 1,
                    SOURCE_RANK.get(source_of(r["asset_id"]), 9))
        canon = min(recs, key=rank)
        # match method across the cluster's edges
        methods = {edges[k] for k in edges if k <= set(members)}
        method = ("plant_code+proximity" if {"plant_code", "proximity"} & methods and len(methods) > 1
                  or "plant_code+proximity" in methods
                  else "plant_code" if methods == {"plant_code"}
                  else "proximity")
        # max pairwise distance among geolocated members
        pts = [_coords(r) for r in recs if _coords(r)]
        maxd = None
        if len(pts) >= 2:
            maxd = max(haversine_m(pts[a], pts[b])
                       for a in range(len(pts)) for b in range(a + 1, len(pts)))
            maxd = round(maxd, 1)
        cid = "AYLX_" + hashlib.sha256("|".join(sorted(members)).encode()).hexdigest()[:12]
        klass = asset_class(canon)
        out.append({
            "cluster_id": cid,
            "canonical_asset_id": canon["asset_id"],
            "asset_class": klass if klass != "other" else asset_class(recs[0]),
            "match_method": method,
            "max_distance_m": maxd,
            "member_asset_ids": sorted(members),
            "members": sorted(({
                "asset_id": r["asset_id"],
                "source": source_of(r["asset_id"]),
                "evidence_tier": r.get("evidence_tier", "T4"),
                "lat": r.get("lat"), "lon": r.get("lon"),
            } for r in recs), key=lambda m: m["asset_id"]),
        })
    return sorted(out, key=lambda c: c["canonical_asset_id"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", default="data/utility_assets.jsonl")
    ap.add_argument("--out", default="data/asset_crosswalk.jsonl")
    ap.add_argument("--plant-m", type=float, default=800.0, help="generation match radius (m)")
    ap.add_argument("--sub-m", type=float, default=400.0, help="substation match radius (m)")
    args = ap.parse_args()

    rows = [json.loads(line) for line in Path(args.assets).read_text().splitlines() if line.strip()]
    power = [r for r in rows if r.get("asset_type") == "power"]
    clusters = build_clusters(power, args.plant_m, args.sub_m)

    # optional schema validation if jsonschema present
    try:
        import jsonschema
        schema = json.loads((REPO / "schemas" / "asset_crosswalk.schema.json").read_text())
        for c in clusters:
            jsonschema.validate(c, schema)
    except ImportError:
        pass

    Path(args.out).write_text("".join(json.dumps(c) + "\n" for c in clusters))

    collapsed = sum(len(c["member_asset_ids"]) for c in clusters)
    by_method: dict[str, int] = {}
    by_class: dict[str, int] = {}
    for c in clusters:
        by_method[c["match_method"]] = by_method.get(c["match_method"], 0) + 1
        by_class[c["asset_class"]] = by_class.get(c["asset_class"], 0) + 1
    unique_after = len(power) - (collapsed - len(clusters))
    print(f"power assets: {len(power)}")
    print(f"clusters (duplicate facilities): {len(clusters)}  spanning {collapsed} rows")
    print(f"  by method: {by_method}")
    print(f"  by class:  {by_class}")
    print(f"deduplicated facility count: {unique_after}  (−{collapsed - len(clusters)} dup rows)")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
