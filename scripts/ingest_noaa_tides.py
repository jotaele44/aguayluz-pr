#!/usr/bin/env python3
"""Ingest NOAA CO-OPS tide-gauge water levels for Puerto Rico.

Fills the *coastal* gap: the producer tracks reservoirs, rivers and (now) groundwater,
but nothing on the coast — where storm surge and coastal flooding threaten low-lying
water/power infrastructure. Source: the NOAA CO-OPS datagetter
(``api.tidesandcurrents.noaa.gov/api/prod/datagetter``, ``product=water_level``), a
federal T1 feed. Writes BOTH halves in one run:

  * assets   -> ``data/utility_assets.jsonl`` (asset_type=water, subtype=tide_gauge)
  * readings -> ``data/coastal_levels.jsonl`` (monitoring_reading, metric=coastal_water_level)

Sub-daily observations are reduced to the **daily maximum** water level per station —
the surge-relevant statistic. The HYDRO_OPS ``coastal_alerts`` proxy flags a gauge whose
latest daily-max sits in its own high tail (surge / coastal flood). Consistent with the
reservoir/aquifer proxies, no absolute NWS coastal-flood threshold is fabricated.

Tide-gauge ``asset_id`` uses the ``NOAA_<station>`` prefix so it never collides with the
USGS water/groundwater rows or the OSM water layer.

    python scripts/ingest_noaa_tides.py --days 90                     # live
    python scripts/ingest_noaa_tides.py --src tides_9755371.json ...  # offline cache
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

DATAGETTER_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

#: PR / island CO-OPS water-level stations (id, display name, lat, lon). Coordinates are
#: the published station locations; those outside the utility_asset PR bounds keep no
#: coordinate rather than being clamped.
PR_STATIONS: list[dict[str, Any]] = [
    {"id": "9755371", "name": "San Juan, La Puntilla", "lat": 18.4592, "lon": -66.1164},
    {"id": "9759110", "name": "Magueyes Island", "lat": 17.9701, "lon": -67.0464},
    {"id": "9759394", "name": "Esperanza, Vieques", "lat": 18.0919, "lon": -65.4711},
    {"id": "9752695", "name": "Culebra", "lat": 18.3011, "lon": -65.3025},
    {"id": "9759938", "name": "Mona Island", "lat": 18.0894, "lon": -67.9389},
]

# utility_asset PR bounds (mainland + Vieques + Culebra + Mona).
LAT_MIN, LAT_MAX = 17.7, 18.7
LON_MIN, LON_MAX = -67.95, -65.2


def _confidence(has_coords: bool = True) -> int:
    try:
        from aguayluz.confidence import score

        return int(score("T1", has_coords=has_coords))
    except Exception:  # noqa: BLE001
        return 80 if has_coords else 65


# ── source acquisition ────────────────────────────────────────────────────────
#: CO-OPS caps a single water_level request at 31 days, so long ranges are chunked.
_CHUNK_DAYS = 30


def fetch_station_live(station_id: str, days: int) -> dict[str, Any]:
    """Fetch hourly water level for a station, chunked to respect the 31-day API cap.

    Returns one merged datagetter-shaped doc (metadata + concatenated data), so the rest
    of the pipeline treats it exactly like a single response or an offline ``--src`` file.
    """
    import httpx

    end = date.today()
    start = end - timedelta(days=days)
    metadata: dict[str, Any] = {}
    data: list[dict[str, Any]] = []
    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=_CHUNK_DAYS), end)
        params = {
            "product": "water_level",
            "application": "aguayluz-pr",
            "datum": "MSL",
            "station": station_id,
            "time_zone": "gmt",
            "units": "metric",
            "interval": "h",  # hourly is plenty for a daily-max surge signal
            "format": "json",
            "begin_date": window_start.strftime("%Y%m%d"),
            "end_date": window_end.strftime("%Y%m%d"),
        }
        r = httpx.get(DATAGETTER_URL, params=params, timeout=120)
        r.raise_for_status()
        doc = r.json()
        metadata = metadata or (doc.get("metadata") or {})
        data.extend(doc.get("data") or [])
        window_start = window_end + timedelta(days=1)
    return {"metadata": metadata, "data": data}


# ── build asset rows ──────────────────────────────────────────────────────────
def _station_meta(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort station metadata: prefer the doc's own metadata, fall back to registry."""
    md = doc.get("metadata") or {}
    sid = str(md.get("id") or "").strip()
    if not sid:
        return None
    reg = next((s for s in PR_STATIONS if s["id"] == sid), {})
    try:
        lat = float(md.get("lat"))
        lon = float(md.get("lon"))
    except (TypeError, ValueError):
        lat, lon = reg.get("lat"), reg.get("lon")
    return {
        "id": sid,
        "name": md.get("name") or reg.get("name") or f"NOAA {sid}",
        "lat": lat,
        "lon": lon,
    }


def build_asset(meta: dict[str, Any]) -> dict:
    lat, lon = meta.get("lat"), meta.get("lon")
    in_bounds = (
        isinstance(lat, (int, float)) and isinstance(lon, (int, float))
        and LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX
    )
    row = {
        "asset_id": f"NOAA_{meta['id']}",
        "asset_name": str(meta["name"]).title(),
        "asset_type": "water",
        "asset_subtype": "tide_gauge",
        "operator": "NOAA CO-OPS",
        "municipality": "unknown",
        "geometry_type": "point" if in_bounds else "unknown",
        "status": "active",
        "source_ref": f"NOAA CO-OPS station {meta['id']}",
        "evidence_tier": "T1",
        "confidence": _confidence(in_bounds),
        "review_status": "accepted",
    }
    if in_bounds:
        row["lat"], row["lon"] = round(float(lat), 6), round(float(lon), 6)
    return row


# ── build reading rows (daily max per station) ────────────────────────────────
def build_readings(doc: dict[str, Any]) -> list[dict]:
    meta = _station_meta(doc)
    if meta is None:
        return []
    sid = meta["id"]
    daily_max: dict[str, float] = {}
    for obs in doc.get("data") or []:
        raw = obs.get("v")
        if raw in (None, ""):
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        day = str(obs.get("t") or "")[:10].replace("/", "-")
        if len(day) != 10:
            continue
        if day not in daily_max or val > daily_max[day]:
            daily_max[day] = val
    rows: list[dict] = []
    for day, val in sorted(daily_max.items()):
        rows.append({
            "reading_id": f"AYL_RDG_{day.replace('-', '')}_{sid}_coastal",
            "asset_id": f"NOAA_{sid}",
            "site_no": sid,
            "metric": "coastal_water_level",
            "parameter_code": "water_level",
            "value": round(val, 4),
            "unit": "m",
            "observed_date": day,
            "provisional": True,
            "source_ref": f"NOAA CO-OPS water_level (daily max), station {sid}",
            "evidence_tier": "T1",
            "confidence": _confidence(True),
            "review_status": "accepted",
        })
    return rows


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge_assets(existing: list[dict], gauges: list[dict]) -> list[dict]:
    """Preserve every non-tide-gauge row; (re)place NOAA_* rows."""
    by_id = {
        r["asset_id"]: r
        for r in existing
        if not str(r.get("asset_id", "")).startswith("NOAA_")
    }
    for r in gauges:
        by_id[r["asset_id"]] = r
    return list(by_id.values())


def merge_readings(existing: list[dict], new: list[dict]) -> list[dict]:
    by_id = {r["reading_id"]: r for r in existing}
    for r in new:
        by_id[r["reading_id"]] = r
    return sorted(by_id.values(), key=lambda r: (r["asset_id"], r["observed_date"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", nargs="*", type=Path, help="Local CO-OPS datagetter JSON file(s).")
    ap.add_argument("--assets-out", default="data/utility_assets.jsonl")
    ap.add_argument("--readings-out", default="data/coastal_levels.jsonl")
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    if args.src:
        docs = [json.loads(p.read_text()) for p in args.src]
        origin = ", ".join(str(p) for p in args.src)
    else:
        docs = []
        for st in PR_STATIONS:
            try:
                docs.append(fetch_station_live(st["id"], args.days))
            except Exception as e:  # noqa: BLE001
                print(f"  station {st['id']} fetch failed ({e}); skipping", file=sys.stderr)
        origin = f"live CO-OPS ({len(docs)}/{len(PR_STATIONS)} stations, {args.days}d)"
        if not docs:
            print("no CO-OPS data fetched; pass --src <json> to run offline", file=sys.stderr)
            return 1

    assets: list[dict] = []
    readings: list[dict] = []
    for doc in docs:
        meta = _station_meta(doc)
        if meta is None:
            continue
        assets.append(build_asset(meta))
        readings.extend(build_readings(doc))

    apath = Path(args.assets_out)
    combined_assets = merge_assets(_read_jsonl(apath), assets)
    apath.parent.mkdir(parents=True, exist_ok=True)
    apath.write_text("".join(json.dumps(r) + "\n" for r in combined_assets))

    rpath = Path(args.readings_out)
    combined_readings = merge_readings(_read_jsonl(rpath), readings)
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text("".join(json.dumps(r) + "\n" for r in combined_readings))

    print(f"source: {origin}")
    print(f"wrote {len(assets)} tide-gauge assets -> {apath}")
    print(f"wrote {len(readings)} coastal readings (daily max) -> {rpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
