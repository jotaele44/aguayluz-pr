#!/usr/bin/env python3
"""Ingest the USGS NWIS surface-water network for Puerto Rico into utility_assets.jsonl.

This is the authoritative water-monitoring backbone the OSM-derived ``ingest_water``
layer lacks. Source: the USGS NWIS Site Service (``waterservices.usgs.gov``), a
federal T1 dataset giving every reservoir, streamgage, and irrigation-canal station
in PR with real coordinates.

Why it matters for AguaYLuz: the reservoir/lake stations are the cross-domain
keystone of the water+power nexus — Lago Guajataca, Caonillas, Dos Bocas, La Plata,
Carraízo (Loíza), Patillas, Guayabal, Toa Vaca, Cerrillos, Cidra, Carite, Lucchetti
each feed BOTH the grid's hydroelectric plants AND the PRASA/AAA public water supply.
(The water↔power dependency itself is an analysis-layer relationship, not an asset
attribute, so it is intentionally NOT stamped on these schema-pure rows.)

Mapping → ``schemas/utility_asset.schema.json`` (additionalProperties=false):
  site type  LK            -> asset_type=water, subtype=reservoir | lake
  site type  ST-CA         -> asset_type=water, subtype=irrigation_canal
  site type  ST            -> asset_type=water, subtype=stream_gage
All rows: evidence_tier=T1 (authoritative USGS), review_status=accepted,
confidence via ``aguayluz.confidence.score`` (T1 + coords = 80). Municipality is
resolved by point-in-polygon against ``data/geo/pr_municipios.geojson`` — no
name-string guessing (skill-spec rule 8: no silent substitution).

asset_id = ``USGS_<site_no>`` so rows never collide with power (PWR*) or the OSM
water layer (WTR/WWT/PMP/RSV*). MERGE preserves every non-USGS row and replaces
USGS_* rows. Because ``ingest_water`` rewrites ALL water rows, run this LAST:

    python scripts/ingest_power.py
    python scripts/ingest_water.py
    python scripts/ingest_usgs_water.py            # live fetch (needs network)
    python scripts/ingest_usgs_water.py --src usgs_pr_sites.rdb   # offline cache

Then ``scripts/ingest_usgs_levels.py`` adds the daily time-series for these sites.
The materialized ``data/utility_assets.jsonl`` is committed (small, public-derived).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NWIS_SITE_URL = "https://waterservices.usgs.gov/nwis/site/"
SITE_TYPES = "LK,ST,ST-CA"
# PR bounds per utility_asset.schema.json (mainland + Vieques + Culebra + Mona).
LAT_MIN, LAT_MAX = 17.7, 18.7
LON_MIN, LON_MAX = -67.95, -65.2

REPO = Path(__file__).resolve().parent.parent
MUNI_GEOJSON = REPO / "data" / "geo" / "pr_municipios.geojson"


# ── source acquisition ────────────────────────────────────────────────────────
def fetch_rdb_live() -> str:
    """Pull the PR site table (LK + ST + ST-CA) from the live NWIS site service."""
    import httpx

    params = {"format": "rdb", "stateCd": "PR", "siteType": SITE_TYPES, "siteStatus": "all"}
    r = httpx.get(NWIS_SITE_URL, params=params, timeout=120)
    r.raise_for_status()
    return r.text


def read_rdb_files(paths: list[Path]) -> str:
    return "\n".join(p.read_text() for p in paths)


# ── RDB parsing ───────────────────────────────────────────────────────────────
def parse_rdb(text: str) -> list[dict[str, str]]:
    """Parse USGS tab-delimited RDB into dict rows (skips #comments + format line)."""
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if header is None:
            header = cols
            continue
        if cols and cols[0].endswith("s") and len(cols[0]) <= 4 and not cols[0].isalpha():
            continue  # the "5s 15s 50s ..." field-width line
        if len(cols) < len(header):
            continue
        rows.append(dict(zip(header, cols, strict=False)))
    return rows


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


def _polys(geom: dict[str, Any]) -> list[list]:
    t = geom.get("type")
    c = geom.get("coordinates") or []
    if t == "Polygon":
        return [c[0]] if c else []
    if t == "MultiPolygon":
        return [poly[0] for poly in c if poly]
    return []


def load_municipios(path: Path) -> list[tuple[str, list[list]]]:
    if not path.is_file():
        return []
    doc = json.loads(path.read_text())
    out: list[tuple[str, list[list]]] = []
    for feat in doc.get("features", []):
        name = (feat.get("properties") or {}).get("name")
        if name:
            out.append((name, _polys(feat.get("geometry") or {})))
    return out


def municipality_for(lat: float, lon: float, munis: list[tuple[str, list[list]]]) -> str:
    for name, rings in munis:
        for ring in rings:
            if _point_in_ring(lon, lat, ring):
                return name
    return "unknown"


# ── classification ────────────────────────────────────────────────────────────
def classify(site_tp: str, name: str) -> tuple[str, str]:
    """(asset_subtype, geometry_type) from NWIS site type + station name."""
    up = name.upper()
    if site_tp == "LK":
        if any(k in up for k in ("LAGO", "LAGUNA", "REPRESA", "RESERVOIR", "DAM")):
            return "reservoir", "point"
        return "lake", "point"
    if site_tp == "ST-CA":
        return "irrigation_canal", "point"
    return "stream_gage", "point"


# ── build rows ────────────────────────────────────────────────────────────────
def build_rows(sites: list[dict[str, str]], munis: list[tuple[str, list[list]]]) -> list[dict]:
    try:
        sys.path.insert(0, str(REPO / "src"))
        from aguayluz.confidence import score
    except Exception:
        def score(tier: str, has_coords: bool = True, **_: Any) -> int:  # fallback
            return {"T1": 80, "T2": 60, "T3": 45, "T4": 30}[tier] - (0 if has_coords else 15)

    rows: list[dict] = []
    for s in sites:
        site_no = (s.get("site_no") or "").strip()
        name = (s.get("station_nm") or "").strip()
        site_tp = (s.get("site_tp_cd") or "").strip()
        if not site_no or not name:
            continue
        lat = lon = None
        try:
            la, lo = float(s["dec_lat_va"]), float(s["dec_long_va"])
            if LAT_MIN <= la <= LAT_MAX and LON_MIN <= lo <= LON_MAX:
                lat, lon = round(la, 6), round(lo, 6)
        except (KeyError, ValueError, TypeError):
            pass
        subtype, geom = classify(site_tp, name)
        muni = municipality_for(lat, lon, munis) if (lat is not None and munis) else "unknown"
        row = {
            "asset_id": f"USGS_{site_no}",
            "asset_name": name.title(),
            "asset_type": "water",
            "asset_subtype": subtype,
            "operator": "USGS",
            "municipality": muni,
            "geometry_type": geom if lat is not None else "unknown",
            "status": "active",
            "source_ref": f"USGS NWIS Site Service, site {site_no}",
            "evidence_tier": "T1",
            "confidence": int(score("T1", has_coords=lat is not None)),
            "review_status": "accepted",
        }
        if lat is not None:
            row["lat"], row["lon"] = lat, lon
        rows.append(row)
    return rows


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], usgs: list[dict]) -> list[dict]:
    """Preserve every non-USGS row; (re)place USGS_* rows."""
    by_id = {r["asset_id"]: r for r in existing if not str(r.get("asset_id", "")).startswith("USGS_")}
    for r in usgs:
        by_id[r["asset_id"]] = r
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", nargs="*", type=Path,
                    help="Local NWIS RDB file(s) to read instead of live fetch.")
    ap.add_argument("--out", default="data/utility_assets.jsonl")
    ap.add_argument("--muni-geojson", default=str(MUNI_GEOJSON))
    args = ap.parse_args()

    if args.src:
        text = read_rdb_files(args.src)
        origin = ", ".join(str(p) for p in args.src)
    else:
        try:
            text = fetch_rdb_live()
            origin = "live NWIS site service"
        except Exception as e:  # noqa: BLE001
            print(f"live fetch failed ({e}); pass --src <rdb file> to run offline", file=sys.stderr)
            return 1

    sites = parse_rdb(text)
    munis = load_municipios(Path(args.muni_geojson))
    rows = build_rows(sites, munis)

    out = Path(args.out)
    combined = merge(_read_jsonl(out), rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))

    sub: dict[str, int] = {}
    for r in rows:
        sub[r["asset_subtype"]] = sub.get(r["asset_subtype"], 0) + 1
    located = sum(1 for r in rows if "lat" in r)
    print(f"source: {origin}")
    print(f"wrote {len(rows)} USGS water assets ({located} geolocated) -> {out}")
    print(f"  by subtype: {sub}")
    print(f"  total assets in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
