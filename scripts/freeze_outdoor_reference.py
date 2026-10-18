#!/usr/bin/env python3
"""Freeze the reference bindings the outdoor-condition ingests depend on.

Writes ``data/reference/outdoor_reference.v1.json`` from three public, keyless sources.
Each section records the source URL and the SHA-256 of the exact bytes it was built
from, so a rebuild that changes a binding shows which response changed.

* **marine_zones** — the WFO San Juan marine zones (``api.weather.gov/zones?type=marine
  &area=AM``, ``cwa == SJU``). For each zone, the municipios whose Census polygon lies
  within :data:`MARINE_BUFFER_M` of the zone polygon (geodesic gap between nearest
  points). The zone geometries are 0.3–0.5 MB each and are not committed; only the
  binding and the bytes' hash are.
* **gridpoints** — the NWS forecast grid cell (``/points/{lat},{lon}``) holding each
  municipio's Census internal point (``data/geo/pr_municipios.json``).
* **uv_zips** — per municipio, the ZCTA with the largest land area inside it (U.S. Census
  2020 ZCTA–county relationship file) that EPA's UV service answers for; EPA returns
  HTTP 500 for a few PR ZIPs, so the next-largest is tried. EPA's UV forecast is
  queried by ZIP.

Run when a binding needs revisiting (NWS re-zones, Census releases a new relationship
file); it is not part of the scheduled refresh.

    python scripts/freeze_outdoor_reference.py            # live, keyless (~170 requests)
    python scripts/freeze_outdoor_reference.py --dry-run  # build, print, write nothing
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.hydromet import USER_AGENT  # noqa: E402
from aguayluz.outdoor import (  # noqa: E402
    MUNICIPIO_POLYGONS,
    REFERENCE_FILE,
    REFERENCE_SCHEMA,
    load_municipios,
)

ZONES_URL = "https://api.weather.gov/zones?type=marine&area=AM"
POINTS_URL = "https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
CENSUS_ZCTA_COUNTY_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_county20_natl.txt"
)
EPA_UV_URL = "https://data.epa.gov/efservice/getEnvirofactsUVDAILY/ZIP/{zip}/JSON"
#: ZCTAs tried per municipio, largest land area first.
UV_ZIP_CANDIDATES = 4
WFO = "SJU"
#: A marine zone applies to a municipio whose polygon lies within this gap of the zone.
MARINE_BUFFER_M = 2000.0


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _get(client: Any, url: str, *, accept: str = "application/geo+json") -> bytes:
    from aguayluz.http_retry import get_with_retry

    response = get_with_retry(url, headers={"Accept": accept}, client=client)
    response.raise_for_status()
    return response.content


def marine_zones(client: Any, municipio_shapes: list[tuple[dict, Any]]) -> tuple[list[dict], dict]:
    from shapely.geometry import shape
    from shapely.ops import nearest_points

    from aguayluz.hydromet.spatial import _haversine_m

    listing = _get(client, ZONES_URL)
    features = json.loads(listing).get("features") or []
    zones = []
    for feature in features:
        props = feature.get("properties") or {}
        if WFO not in (props.get("cwa") or []):
            continue
        url = props.get("@id") or feature.get("id")
        payload = _get(client, url)
        geometry = json.loads(payload).get("geometry")
        if not geometry:
            raise RuntimeError(f"{props.get('id')}: zone response has no geometry")
        zone_geom = shape(geometry)
        bound = []
        for municipio, geom in municipio_shapes:
            if zone_geom.intersects(geom):
                gap = 0.0
            else:
                a, b = nearest_points(geom, zone_geom)
                gap = _haversine_m(a.x, a.y, b.x, b.y)
            if gap <= MARINE_BUFFER_M:
                bound.append({"geoid": municipio["geoid"], "name": municipio["name"],
                              "distance_m": round(gap, 1)})
        zones.append({
            "zone_id": props.get("id"),
            "name": props.get("name"),
            "zone_type": props.get("type"),
            "source_url": url,
            "byte_sha256": sha256(payload).hexdigest(),
            "municipios": sorted(bound, key=lambda m: m["geoid"]),
        })
    zones.sort(key=lambda z: z["zone_id"])
    return zones, {"source_url": ZONES_URL, "byte_sha256": sha256(listing).hexdigest(),
                   "binding": f"municipio polygon within {MARINE_BUFFER_M:.0f} m of the zone polygon"}


def gridpoints(client: Any, municipios: list[dict]) -> tuple[list[dict], dict]:
    rows = []
    for municipio in municipios:
        url = POINTS_URL.format(lat=municipio["lat"], lon=municipio["lon"])
        payload = _get(client, url)
        props = json.loads(payload).get("properties") or {}
        rows.append({
            "geoid": municipio["geoid"],
            "name": municipio["name"],
            "lat": municipio["lat"],
            "lon": municipio["lon"],
            "grid_id": props.get("gridId"),
            "grid_x": props.get("gridX"),
            "grid_y": props.get("gridY"),
            "forecast_zone": str(props.get("forecastZone") or "").rsplit("/", 1)[-1] or None,
            "county_zone": str(props.get("county") or "").rsplit("/", 1)[-1] or None,
            "source_url": url,
            "byte_sha256": sha256(payload).hexdigest(),
        })
    return rows, {"source_url": POINTS_URL, "binding": "grid cell holding the Census internal point"}


def uv_zips(client: Any, municipios: list[dict]) -> tuple[list[dict], dict]:
    payload = _get(client, CENSUS_ZCTA_COUNTY_URL, accept="text/plain")
    text = payload.decode("utf-8-sig")
    lines = text.splitlines()
    header = lines[0].split("|")
    col = {name: i for i, name in enumerate(header)}
    ranked: dict[str, list[tuple[int, str, int]]] = {}
    for line in lines[1:]:
        parts = line.split("|")
        county, zcta = parts[col["GEOID_COUNTY_20"]], parts[col["GEOID_ZCTA5_20"]]
        if not county.startswith("72") or not zcta:
            continue
        ranked.setdefault(county, []).append(
            (int(parts[col["AREALAND_PART"]] or 0), zcta, int(parts[col["AREALAND_COUNTY_20"]] or 0)))
    rows = []
    for municipio in municipios:
        candidates = sorted(ranked.get(municipio["geoid"], []), reverse=True)[:UV_ZIP_CANDIDATES]
        chosen, tried = None, []
        # EPA's UV service answers HTTP 500 for some ZIPs (00637 Sabana Grande, 00962
        # Cataño when this was written): take the largest ZCTA EPA actually serves.
        for part, zcta, county_land in candidates:
            tried.append(zcta)
            if _epa_uv_serves(client, zcta):
                chosen = (part, zcta, county_land)
                break
        rows.append({
            "geoid": municipio["geoid"],
            "name": municipio["name"],
            "zip": chosen[1] if chosen else None,
            "zip_rank": tried.index(chosen[1]) + 1 if chosen else None,
            "zips_tried": tried,
            "land_share_of_municipio": round(chosen[0] / chosen[2], 4) if chosen and chosen[2] else None,
        })
    return rows, {"source_url": CENSUS_ZCTA_COUNTY_URL, "byte_sha256": sha256(payload).hexdigest(),
                  "binding": "largest-land-area ZCTA inside the municipio (county GEOID) that EPA's "
                             "UV service answers for", "coverage_check": EPA_UV_URL}


def _epa_uv_serves(client: Any, zcta: str) -> bool:
    try:
        rows = json.loads(_get(client, EPA_UV_URL.format(zip=zcta), accept="application/json"))
    except Exception:  # noqa: BLE001 - an EPA error means "not served", try the next ZCTA
        return False
    return isinstance(rows, list) and any(
        isinstance(r, dict) and str(r.get("STATE") or "").upper() == "PR" for r in rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=REFERENCE_FILE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    import httpx
    from shapely.geometry import shape

    municipios = load_municipios()
    polygons = json.loads(MUNICIPIO_POLYGONS.read_text(encoding="utf-8"))
    by_geoid = {m["geoid"]: m for m in municipios}
    shapes = [(by_geoid[str(f["properties"]["geoid"])], shape(f["geometry"]))
              for f in polygons["features"]]
    with httpx.Client(timeout=120, follow_redirects=True,
                      headers={"User-Agent": USER_AGENT}) as client:
        zones, zones_src = marine_zones(client, shapes)
        grid, grid_src = gridpoints(client, municipios)
        zips, zips_src = uv_zips(client, municipios)

    unresolved = []
    if any(not g["grid_id"] for g in grid):
        unresolved.append("MUNICIPIO_WITHOUT_GRIDPOINT")
    if any(not z["zip"] for z in zips):
        unresolved.append("MUNICIPIO_WITHOUT_ZCTA")
    payload = {
        "schema_version": REFERENCE_SCHEMA,
        "generated_at": _iso(datetime.now(timezone.utc)),
        "generated_by": "scripts/freeze_outdoor_reference.py",
        "sources": {"marine_zones": zones_src, "gridpoints": grid_src, "uv_zips": zips_src},
        "marine_zones": zones,
        "gridpoints": grid,
        "uv_zips": zips,
        "unresolved_material": unresolved,
    }
    summary = {
        "marine_zones": len(zones),
        "coastal_zone_bindings": sum(len(z["municipios"]) for z in zones),
        "gridpoints": sum(1 for g in grid if g["grid_id"]),
        "uv_zips": sum(1 for z in zips if z["zip"]),
        "unresolved": unresolved,
    }
    print(json.dumps(summary, indent=2))
    if args.dry_run:
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0 if not unresolved else 1


if __name__ == "__main__":
    raise SystemExit(main())
