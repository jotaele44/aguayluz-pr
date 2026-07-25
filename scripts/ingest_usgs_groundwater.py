#!/usr/bin/env python3
"""Ingest the USGS NWIS groundwater network for Puerto Rico.

Fills the *aquifer* gap: the surface-water backbone (``ingest_usgs_water`` +
``ingest_usgs_levels``) covers reservoirs and streams, but not the groundwater wells
whose water table is PR's leading drought / supply signal — a well draws down before
surface shortage is visible. Source: the USGS NWIS Site Service (``siteType=GW``) and
the NWIS Daily Values service (``waterservices.usgs.gov/nwis/dv``, param 72019), a
federal T1 feed. This script writes BOTH halves in one run:

  * assets   -> ``data/utility_assets.jsonl`` (asset_type=water, subtype=groundwater_well)
  * readings -> ``data/groundwater_levels.jsonl`` (monitoring_reading, metric=groundwater_level)

Metric captured: USGS parameter **72019** — depth to water level below land surface (ft).
A HIGH reading means a DEEPER water table, i.e. aquifer drawdown; the HYDRO_OPS
``aquifer_alerts`` proxy flags a site whose latest depth sits in its own high tail.
Like the reservoir proxy, no absolute "critical" threshold is fabricated — official
well operating levels are not public (skill-spec rule 8: no silent substitution).

Groundwater ``asset_id`` uses the ``USGSGW_<site>`` prefix (NOT ``USGS_``) so the
surface-water ``ingest_usgs_water`` merge — which replaces every ``USGS_*`` row — never
wipes these wells.

    python scripts/ingest_usgs_groundwater.py                       # live
    python scripts/ingest_usgs_groundwater.py --src-sites gw.rdb --src-levels gw.json  # offline

Reuses the RDB parser + point-in-polygon municipality resolver from
``scripts/ingest_usgs_water.py``. Both output files are committed (small, public-derived).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

# Reuse the surface-water ingester's RDB + municipality helpers (no duplication).
from ingest_usgs_water import (  # noqa: E402
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    MUNI_GEOJSON,
    load_municipios,
    municipality_for,
    parse_rdb,
)

NWIS_SITE_URL = "https://waterservices.usgs.gov/nwis/site/"
# Groundwater daily values ride the SAME NWIS Daily Values endpoint the reservoir/river
# ingester (ingest_usgs_levels.py) uses — one endpoint for all USGS time-series, so a
# future migration moves them together. (The legacy /nwis/gwlevels/ service is being
# decommissioned; discrete field measurements it served are out of scope here.)
NWIS_DV_URL = "https://waterservices.usgs.gov/nwis/dv/"
#: Depth to water level below land surface (ft) — the aquifer-drawdown signal.
GW_PARAM = "72019"


def _confidence(has_coords: bool, provisional: bool = False) -> int:
    try:
        from aguayluz.confidence import score

        base = int(score("T1", has_coords=has_coords))
    except Exception:  # noqa: BLE001
        base = 80 if has_coords else 65
    return max(0, base - (5 if provisional else 0))


# ── source acquisition ────────────────────────────────────────────────────────
def fetch_sites_live() -> str:
    import httpx

    params = {"format": "rdb", "stateCd": "PR", "siteType": "GW", "siteStatus": "all"}
    r = httpx.get(NWIS_SITE_URL, params=params, timeout=120)
    r.raise_for_status()
    return r.text


def fetch_levels_live(sites: list[str], days: int) -> list[dict[str, Any]]:
    import httpx

    end = date.today()
    start = end - timedelta(days=days)
    docs: list[dict[str, Any]] = []
    for i in range(0, len(sites), 50):
        chunk = sites[i : i + 50]
        params = {
            "format": "json",
            "sites": ",".join(chunk),
            "parameterCd": GW_PARAM,
            "startDT": start.isoformat(),
            "endDT": end.isoformat(),
            "siteStatus": "all",
        }
        r = httpx.get(NWIS_DV_URL, params=params, timeout=120)
        r.raise_for_status()
        docs.append(r.json())
    return docs


# ── build asset rows ──────────────────────────────────────────────────────────
def build_assets(
    sites: list[dict[str, str]], munis: list[tuple[str, list[list]]]
) -> list[dict]:
    rows: list[dict] = []
    for s in sites:
        site_no = (s.get("site_no") or "").strip()
        name = (s.get("station_nm") or "").strip()
        if not site_no or not name:
            continue
        lat = lon = None
        try:
            la, lo = float(s["dec_lat_va"]), float(s["dec_long_va"])
            if LAT_MIN <= la <= LAT_MAX and LON_MIN <= lo <= LON_MAX:
                lat, lon = round(la, 6), round(lo, 6)
        except (KeyError, ValueError, TypeError):
            pass
        muni = municipality_for(lat, lon, munis) if (lat is not None and munis) else "unknown"
        row = {
            "asset_id": f"USGSGW_{site_no}",
            "asset_name": name.title(),
            "asset_type": "water",
            "asset_subtype": "groundwater_well",
            "operator": "USGS",
            "municipality": muni,
            "geometry_type": "point" if lat is not None else "unknown",
            "status": "active",
            "source_ref": f"USGS NWIS Site Service (GW), site {site_no}",
            "evidence_tier": "T1",
            "confidence": _confidence(lat is not None),
            "review_status": "accepted",
        }
        if lat is not None:
            row["lat"], row["lon"] = lat, lon
        rows.append(row)
    return rows


# ── build reading rows ────────────────────────────────────────────────────────
def build_readings(docs: list[dict[str, Any]]) -> list[dict]:
    rows: list[dict] = []
    for doc in docs:
        for ts in (doc.get("value") or {}).get("timeSeries") or []:
            src = ts.get("sourceInfo") or {}
            site_no = ((src.get("siteCode") or [{}])[0]).get("value", "")
            if not site_no:
                continue
            var = ts.get("variable") or {}
            pcode = (var.get("variableCode") or [{}])[0].get("value", "") or GW_PARAM
            unit = ((var.get("unit") or {}).get("unitCode")) or "ft"
            for block in ts.get("values") or []:
                for v in block.get("value") or []:
                    raw = v.get("value")
                    if raw in (None, "", "-999999", "-999999.0"):
                        continue
                    try:
                        val = float(raw)
                    except (TypeError, ValueError):
                        continue
                    day = (v.get("dateTime") or "")[:10]
                    if len(day) != 10:
                        continue
                    provisional = "P" in (v.get("qualifiers") or [])
                    rid = f"AYL_RDG_{day.replace('-', '')}_{site_no}_gw"
                    rows.append({
                        "reading_id": rid,
                        "asset_id": f"USGSGW_{site_no}",
                        "site_no": site_no,
                        "metric": "groundwater_level",
                        "parameter_code": pcode,
                        "value": val,
                        "unit": unit,
                        "observed_date": day,
                        "provisional": provisional,
                        "source_ref": f"USGS NWIS Groundwater Levels, site {site_no} parm {pcode}",
                        "evidence_tier": "T1",
                        "confidence": _confidence(True, provisional),
                        "review_status": "accepted",
                    })
    return rows


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge_assets(existing: list[dict], gw: list[dict]) -> list[dict]:
    """Preserve every non-groundwater-well row; (re)place USGSGW_* rows."""
    by_id = {
        r["asset_id"]: r
        for r in existing
        if not str(r.get("asset_id", "")).startswith("USGSGW_")
    }
    for r in gw:
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
    ap.add_argument("--src-sites", type=Path, help="Local NWIS GW site RDB file.")
    ap.add_argument("--src-levels", nargs="*", type=Path, help="Local NWIS gwlevels JSON file(s).")
    ap.add_argument("--assets-out", default="data/utility_assets.jsonl")
    ap.add_argument("--readings-out", default="data/groundwater_levels.jsonl")
    ap.add_argument("--muni-geojson", default=str(MUNI_GEOJSON))
    ap.add_argument("--days", type=int, default=365)
    args = ap.parse_args()

    # sites → assets
    if args.src_sites:
        site_text = args.src_sites.read_text()
        origin = str(args.src_sites)
    else:
        try:
            site_text = fetch_sites_live()
            origin = "live NWIS GW site service"
        except Exception as e:  # noqa: BLE001
            print(f"live site fetch failed ({e}); pass --src-sites <rdb>", file=sys.stderr)
            return 1
    sites = parse_rdb(site_text)
    munis = load_municipios(Path(args.muni_geojson))
    assets = build_assets(sites, munis)

    # levels → readings
    if args.src_levels:
        docs = [json.loads(p.read_text()) for p in args.src_levels]
    else:
        site_nos = [s.get("site_no", "").strip() for s in sites if s.get("site_no")]
        try:
            docs = fetch_levels_live(site_nos, args.days) if site_nos else []
        except Exception as e:  # noqa: BLE001
            print(f"live gwlevels fetch failed ({e}); pass --src-levels <json>", file=sys.stderr)
            return 1
    readings = build_readings(docs)

    # Keep only wells that actually carry a time series — an aquifer monitor cares about
    # the monitored subset, not every historical one-off measurement site. This keeps the
    # asset corpus lean and every GW well linkable to a real reading stream.
    monitored = {r["site_no"] for r in readings}
    if monitored:
        assets = [a for a in assets if a["asset_id"].removeprefix("USGSGW_") in monitored]

    apath = Path(args.assets_out)
    combined_assets = merge_assets(_read_jsonl(apath), assets)
    apath.parent.mkdir(parents=True, exist_ok=True)
    apath.write_text("".join(json.dumps(r) + "\n" for r in combined_assets))

    rpath = Path(args.readings_out)
    combined_readings = merge_readings(_read_jsonl(rpath), readings)
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text("".join(json.dumps(r) + "\n" for r in combined_readings))

    located = sum(1 for r in assets if "lat" in r)
    print(f"source: {origin}")
    print(f"wrote {len(assets)} GW well assets ({located} geolocated) -> {apath}")
    print(f"wrote {len(readings)} GW readings -> {rpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
