#!/usr/bin/env python3
"""Ingest NOAA NCEI precipitation and compute a percent-of-normal drought corroboration signal.

USDM's Puerto Rico classification (``scripts/ingest_drought_usdm.py``) leans on a
comparatively sparse local observation network, so this adds an independent
precipitation-based signal to cross-check it: **percent-of-normal precipitation**, a
standard NOAA-recognized companion indicator to USDM/SPI. A full Standardized
Precipitation Index needs enough retained station history to fit a gamma distribution
per station/window, which this repo doesn't have yet — percent-of-normal needs only
observed rainfall plus the published 1991-2020 climate normals, so it's shipped now and
true SPI is a natural follow-on once this ingest has accumulated sufficient history.
No threshold is invented beyond that: <50% of normal over a rolling window is NOAA's
own commonly-cited "significantly below normal" band, used here as the parameter and
nothing tighter.

Source: NOAA NCEI's keyless Data Service API (``www.ncei.noaa.gov/access/services/data/v1``
— no API token required, unlike the older CDO Web Services v2), two datasets:

  * ``daily-summaries`` (element ``PRCP``) — observed daily rainfall.
  * ``normals-monthly`` (element ``MLY-PRCP-NORMAL``) — 1991-2020 climatological normals.

Both requested with ``units=metric`` (verified live: normals-monthly is natively
hundredths-of-inch and daily-summaries is natively tenths-of-mm — ``units=metric``
sidesteps that mismatch entirely by returning both already in mm).

For each station and each day D with enough coverage in the fetched window, the 30-day
and 90-day accumulated rainfall ending on D is compared against the *calendar-weighted*
climatological normal for that same span (each involved month's normal prorated to its
per-day rate, summed across the window) — not a flat "this month's normal", which would
misstate a window straddling a month boundary. A window is skipped (not zero-filled) when
fewer than 70% of its days have an observed value — a real gap, not an invented reading.

Five stations chosen for geographic spread across PR (north/San Juan, northwest/
Aguadilla, east/Ceiba, south/Aguirre — the historically driest region, central-mountain/
Toro Negro), each live-verified to have both daily-summaries PRCP and normals-monthly
MLY-PRCP-NORMAL coverage.

  * assets   -> ``data/utility_assets.jsonl`` (asset_type=water, subtype=precipitation_gauge)
  * readings -> ``data/precipitation_conditions.jsonl`` (metric=precipitation_pct_normal)

    python scripts/ingest_precip_ncei.py --days 120                          # live
    python scripts/ingest_precip_ncei.py --normals-src n.json --daily-src d.json
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

NCEI_URL = "https://www.ncei.noaa.gov/access/services/data/v1"

#: (station id, display name, lat, lon) — each live-verified for PRCP + MLY-PRCP-NORMAL.
PR_STATIONS: list[dict[str, Any]] = [
    {"id": "RQW00011641", "name": "San Juan L M Marin Intl AP", "lat": 18.4325, "lon": -66.0106},
    {"id": "RQW00011603", "name": "Borinquen AP, Aguadilla", "lat": 18.4981, "lon": -67.1294},
    {"id": "RQW00011630", "name": "Roosevelt Roads, Ceiba", "lat": 18.2553, "lon": -65.6411},
    {"id": "RQC00660152", "name": "Aguirre", "lat": 17.9556, "lon": -66.2222},
    {"id": "RQC00669432", "name": "Toro Negro Forest", "lat": 18.1731, "lon": -66.4928},
]
STATION_IDS = [s["id"] for s in PR_STATIONS]

#: Rolling windows computed, and the minimum fraction of days in a window that must
#: carry an observed value before a percent-of-normal is reported for it.
WINDOWS: tuple[int, ...] = (30, 90)
MIN_COVERAGE = 0.7
#: NOAA's own commonly-cited "significantly below normal" band — not tightened here.
SHORTFALL_FLOOR_PCT = 50.0


def _confidence(has_coords: bool = True) -> int:
    try:
        from aguayluz.confidence import score

        return int(score("T1", has_coords=has_coords))
    except Exception:  # noqa: BLE001
        return 80 if has_coords else 65


# ── source acquisition ────────────────────────────────────────────────────────
def fetch_normals_live() -> str:
    import httpx

    params = {
        "dataset": "normals-monthly",
        "stations": ",".join(STATION_IDS),
        "startDate": "2020-01-01",
        "endDate": "2020-12-01",
        "dataTypes": "MLY-PRCP-NORMAL",
        "format": "json",
        "units": "metric",
    }
    r = httpx.get(NCEI_URL, params=params, timeout=120)
    r.raise_for_status()
    return r.text


def fetch_daily_live(start: date, end: date) -> str:
    import httpx

    params = {
        "dataset": "daily-summaries",
        "stations": ",".join(STATION_IDS),
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dataTypes": "PRCP",
        "format": "json",
        "units": "metric",
    }
    r = httpx.get(NCEI_URL, params=params, timeout=120)
    r.raise_for_status()
    return r.text


# ── normals: station -> {month(1-12) -> normal mm, per-day rate mm/day} ───────
def parse_normals(raw: str) -> dict[str, dict[int, float]]:
    docs = json.loads(raw)
    out: dict[str, dict[int, float]] = {}
    for d in docs:
        val = d.get("MLY-PRCP-NORMAL")
        if val in (None, ""):
            continue
        try:
            mm = float(val)
            month = int(d.get("DATE") or 0)
        except (TypeError, ValueError):
            continue
        if not 1 <= month <= 12:
            continue
        out.setdefault(str(d.get("STATION") or ""), {})[month] = mm
    return out


_DAYS_IN_MONTH = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _daily_normal_rate(station_normals: dict[int, float], month: int) -> float | None:
    total = station_normals.get(month)
    if total is None:
        return None
    return total / _DAYS_IN_MONTH[month]


def window_normal_mm(station_normals: dict[int, float], end: date, days: int) -> float | None:
    """Calendar-weighted normal for the `days`-day window ending on `end` (inclusive)."""
    total = 0.0
    d = end - timedelta(days=days - 1)
    while d <= end:
        rate = _daily_normal_rate(station_normals, d.month)
        if rate is None:
            return None
        total += rate
        d += timedelta(days=1)
    return total


# ── daily observations: station -> {date -> mm} ───────────────────────────────
def parse_daily(raw: str) -> dict[str, dict[str, float]]:
    docs = json.loads(raw)
    out: dict[str, dict[str, float]] = {}
    for d in docs:
        val = d.get("PRCP")
        if val in (None, ""):
            continue
        try:
            mm = float(val)
        except (TypeError, ValueError):
            continue
        station = str(d.get("STATION") or "")
        day = str(d.get("DATE") or "")[:10]
        if station and len(day) == 10:
            out.setdefault(station, {})[day] = mm
    return out


def window_observed_mm(daily: dict[str, float], end: date, days: int) -> tuple[float, float]:
    """Returns (sum_mm, coverage_fraction) over the `days`-day window ending on `end`."""
    total = 0.0
    have = 0
    d = end - timedelta(days=days - 1)
    while d <= end:
        v = daily.get(d.isoformat())
        if v is not None:
            total += v
            have += 1
        d += timedelta(days=1)
    return total, have / days


# ── build asset + reading rows ─────────────────────────────────────────────
def build_asset(station: dict[str, Any]) -> dict:
    return {
        "asset_id": f"NCEI_{station['id']}",
        "asset_name": str(station["name"]).title(),
        "asset_type": "water",
        "asset_subtype": "precipitation_gauge",
        "operator": "NOAA NCEI (GHCN-Daily)",
        "municipality": "unknown",
        "lat": station["lat"],
        "lon": station["lon"],
        "geometry_type": "point",
        "status": "active",
        "source_ref": f"NOAA NCEI GHCN-Daily station {station['id']}",
        "evidence_tier": "T1",
        "confidence": _confidence(True),
        "review_status": "accepted",
    }


def build_readings(
    station_id: str,
    daily: dict[str, float],
    normals: dict[int, float],
    fetch_start: date,
    fetch_end: date,
) -> list[dict]:
    rows: list[dict] = []
    for window in WINDOWS:
        d = fetch_start + timedelta(days=window - 1)
        while d <= fetch_end:
            observed_mm, coverage = window_observed_mm(daily, d, window)
            if coverage < MIN_COVERAGE:
                d += timedelta(days=1)
                continue
            normal_mm = window_normal_mm(normals, d, window)
            if not normal_mm:
                d += timedelta(days=1)
                continue
            pct = round(100.0 * observed_mm / normal_mm, 1)
            day_str = d.isoformat()
            rows.append({
                "reading_id": f"AYL_RDG_{day_str.replace('-', '')}_{station_id}_precip{window}d",
                "asset_id": f"NCEI_{station_id}",
                "site_no": station_id,
                "metric": "precipitation_pct_normal",
                "parameter_code": f"{window}d",
                "value": pct,
                "unit": "%",
                "observed_date": day_str,
                "provisional": True,
                "source_ref": "NOAA NCEI GHCN-Daily vs 1991-2020 monthly normals (calendar-weighted)",
                "evidence_tier": "T1",
                "confidence": _confidence(True),
                "review_status": "accepted",
            })
            d += timedelta(days=1)
    return rows


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge_assets(existing: list[dict], gauges: list[dict]) -> list[dict]:
    by_id = {r["asset_id"]: r for r in existing if not str(r.get("asset_id", "")).startswith("NCEI_")}
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
    ap.add_argument("--normals-src", type=Path, help="Local normals-monthly JSON (offline mode).")
    ap.add_argument("--daily-src", type=Path, help="Local daily-summaries JSON (offline mode).")
    ap.add_argument("--assets-out", default="data/utility_assets.jsonl")
    ap.add_argument("--readings-out", default="data/precipitation_conditions.jsonl")
    ap.add_argument("--days", type=int, default=120,
                    help="Days of daily observations to fetch (windows need +90d lookback within this).")
    args = ap.parse_args()

    if args.normals_src:
        normals_raw = args.normals_src.read_text()
    else:
        try:
            normals_raw = fetch_normals_live()
        except Exception as e:  # noqa: BLE001
            print(f"live NCEI normals fetch failed ({e}); pass --normals-src <json>", file=sys.stderr)
            return 1

    fetch_end = date.today()
    fetch_start = fetch_end - timedelta(days=args.days)
    if args.daily_src:
        daily_raw = args.daily_src.read_text()
    else:
        try:
            daily_raw = fetch_daily_live(fetch_start, fetch_end)
        except Exception as e:  # noqa: BLE001
            print(f"live NCEI daily fetch failed ({e}); pass --daily-src <json>", file=sys.stderr)
            return 1

    normals_by_station = parse_normals(normals_raw)
    daily_by_station = parse_daily(daily_raw)

    assets = [build_asset(s) for s in PR_STATIONS]
    readings: list[dict] = []
    for station in PR_STATIONS:
        sid = station["id"]
        readings.extend(
            build_readings(
                sid,
                daily_by_station.get(sid, {}),
                normals_by_station.get(sid, {}),
                fetch_start,
                fetch_end,
            )
        )

    apath = REPO / args.assets_out
    combined_assets = merge_assets(_read_jsonl(apath), assets)
    apath.parent.mkdir(parents=True, exist_ok=True)
    apath.write_text("".join(json.dumps(r) + "\n" for r in combined_assets))

    rpath = REPO / args.readings_out
    combined_readings = merge_readings(_read_jsonl(rpath), readings)
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text("".join(json.dumps(r) + "\n" for r in combined_readings))

    print(f"source: {'offline fixtures' if args.normals_src or args.daily_src else 'live NCEI Data Service'}")
    print(f"wrote {len(assets)} precipitation-gauge assets -> {apath}")
    print(f"wrote {len(readings)} percent-of-normal readings ({'/'.join(f'{w}d' for w in WINDOWS)}) -> {rpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
