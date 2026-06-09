#!/usr/bin/env python3
"""Ingest USGS daily reservoir levels + streamflow for PR into monitoring_readings.

This is the time-series half of the monitoring system — the live water signal that
``ingest_usgs_water`` (assets) cannot carry. Source: the USGS NWIS Daily Values
service (``waterservices.usgs.gov/nwis/dv``), a federal T1 feed. Each daily value
becomes a schema-valid ``monitoring_reading`` (schemas/monitoring_reading.schema.json)
linked by ``asset_id`` to the ``USGS_<site>`` utility_asset rows.

Metrics captured (USGS parameter codes):
  72375 / 72379  reservoir/lake water-surface elevation (ft)  -> metric=reservoir_elevation
  00054 / 62614  reservoir storage / elevation variants        -> reservoir_elevation
  62615          lake elevation NAVD88 (ft)                     -> reservoir_elevation
  00060          streamflow (ft3/s)                             -> metric=streamflow
  00065          gage height (ft)                               -> metric=gage_height

Reservoir elevation is PR's operational drought signal (AAA tracks the marquee
supply lakes — Carraízo/Loíza, La Plata, Guajataca, Patillas, Toa Vaca, …, which
are ALSO the grid's hydro reservoirs). NOTE: this script records the measured
truth only. Deriving "low/critical" service_events requires the official AAA
operating levels (niveles de observación/ajuste/control) per reservoir; those are
NOT public per-site constants, so no threshold events are fabricated here
(skill-spec rule 8 — no silent substitution). The hook is documented in the
coverage report.

Run AFTER ingest_usgs_water (needs the asset_ids to link to):
    python scripts/ingest_usgs_levels.py --days 60                 # live
    python scripts/ingest_usgs_levels.py --src dv.json [dv2.json]  # offline cache

Writes data/reservoir_levels.jsonl (committed; small, public-derived). Merge is
idempotent by reading_id (asset/metric/day).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

NWIS_DV_URL = "https://waterservices.usgs.gov/nwis/dv/"
RESERVOIR_PARAMS = ["72375", "72379", "00054", "62614", "62615"]
FLOW_PARAMS = ["00060", "00065"]
ALL_PARAMS = RESERVOIR_PARAMS + FLOW_PARAMS

METRIC_BY_PARAM = {
    "72375": ("reservoir_elevation", "ft"),
    "72379": ("reservoir_elevation", "ft"),
    "62614": ("reservoir_elevation", "ft"),
    "62615": ("reservoir_elevation", "ft"),
    "00054": ("reservoir_storage_pct", "%"),
    "00060": ("streamflow", "ft3/s"),
    "00065": ("gage_height", "ft"),
}

REPO = Path(__file__).resolve().parent.parent


# ── source acquisition ────────────────────────────────────────────────────────
def reservoir_site_nos(assets_path: Path) -> list[str]:
    """USGS site numbers whose utility_asset is a reservoir/lake/stream_gage."""
    if not assets_path.is_file():
        return []
    sites: list[str] = []
    for ln in assets_path.read_text().splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        aid = str(r.get("asset_id", ""))
        if aid.startswith("USGS_") and r.get("asset_type") == "water":
            sites.append(aid.removeprefix("USGS_"))
    return sites


def fetch_dv_live(sites: list[str], days: int) -> list[dict[str, Any]]:
    import httpx

    end = date.today()
    start = end - timedelta(days=days)
    docs: list[dict[str, Any]] = []
    # NWIS allows multi-site requests; chunk to keep URLs sane.
    for i in range(0, len(sites), 50):
        chunk = sites[i : i + 50]
        params = {
            "format": "json",
            "sites": ",".join(chunk),
            "parameterCd": ",".join(ALL_PARAMS),
            "startDT": start.isoformat(),
            "endDT": end.isoformat(),
            "siteStatus": "all",
        }
        r = httpx.get(NWIS_DV_URL, params=params, timeout=120)
        r.raise_for_status()
        docs.append(r.json())
    return docs


def read_dv_files(paths: list[Path]) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in paths]


# ── parse WaterML-JSON → rows ─────────────────────────────────────────────────
def _confidence(provisional: bool) -> int:
    try:
        sys.path.insert(0, str(REPO / "src"))
        from aguayluz.confidence import score

        base = score("T1", has_coords=True)
    except Exception:
        base = 80
    return max(0, base - (5 if provisional else 0))


def rows_from_doc(doc: dict[str, Any]) -> list[dict]:
    rows: list[dict] = []
    series_list = (doc.get("value") or {}).get("timeSeries") or []
    for ts in series_list:
        src = ts.get("sourceInfo") or {}
        codes = src.get("siteCode") or [{}]
        site_no = codes[0].get("value", "")
        var = ts.get("variable") or {}
        pcode = (var.get("variableCode") or [{}])[0].get("value", "")
        metric, default_unit = METRIC_BY_PARAM.get(pcode, ("other", ""))
        unit = ((var.get("unit") or {}).get("unitCode")) or default_unit or "unknown"
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
                if not day:
                    continue
                provisional = "P" in (v.get("qualifiers") or [])
                # Include parameter_code so distinct series that share a metric
                # (e.g. elevation in LMSL 72375 vs PR Datum 2002 72379) don't collide.
                rid = f"AYL_RDG_{day.replace('-', '')}_{site_no}_{pcode}"
                rows.append({
                    "reading_id": rid,
                    "asset_id": f"USGS_{site_no}",
                    "site_no": site_no,
                    "metric": metric,
                    "parameter_code": pcode,
                    "value": val,
                    "unit": unit,
                    "observed_date": day,
                    "provisional": provisional,
                    "source_ref": f"USGS NWIS Daily Values, site {site_no} parm {pcode}",
                    "evidence_tier": "T1",
                    "confidence": _confidence(provisional),
                    "review_status": "accepted",
                })
    return rows


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], new: list[dict]) -> list[dict]:
    """Idempotent by reading_id (asset/metric/day); new values win (revisions)."""
    by_id = {r["reading_id"]: r for r in existing}
    for r in new:
        by_id[r["reading_id"]] = r
    return sorted(by_id.values(), key=lambda r: (r["asset_id"], r["metric"], r["observed_date"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", nargs="*", type=Path, help="Local NWIS dv JSON file(s).")
    ap.add_argument("--assets", default="data/utility_assets.jsonl")
    ap.add_argument("--out", default="data/reservoir_levels.jsonl")
    ap.add_argument("--days", type=int, default=60)
    args = ap.parse_args()

    if args.src:
        docs = read_dv_files(args.src)
        origin = ", ".join(str(p) for p in args.src)
    else:
        sites = reservoir_site_nos(Path(args.assets))
        if not sites:
            print("no USGS water assets found — run ingest_usgs_water first", file=sys.stderr)
            return 1
        try:
            docs = fetch_dv_live(sites, args.days)
            origin = f"live NWIS dv ({len(sites)} sites, {args.days}d)"
        except Exception as e:  # noqa: BLE001
            print(f"live fetch failed ({e}); pass --src <dv.json> to run offline", file=sys.stderr)
            return 1

    rows: list[dict] = []
    for d in docs:
        rows.extend(rows_from_doc(d))

    out = Path(args.out)
    combined = merge(_read_jsonl(out), rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))

    by_metric: dict[str, int] = {}
    assets: set[str] = set()
    for r in rows:
        by_metric[r["metric"]] = by_metric.get(r["metric"], 0) + 1
        assets.add(r["asset_id"])
    print(f"source: {origin}")
    print(f"wrote {len(rows)} readings across {len(assets)} assets -> {out}")
    print(f"  by metric: {by_metric}")
    print(f"  total readings in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
