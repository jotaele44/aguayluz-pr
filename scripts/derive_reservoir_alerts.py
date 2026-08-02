#!/usr/bin/env python3
"""Derive reservoir low-level alerts (service_event) from USGS daily levels.

The threshold half of the water monitoring loop. Reads the monitoring_reading
time-series in data/reservoir_levels.jsonl and, for each reservoir with enough
history, emits a schema-valid ``service_event`` when the LATEST elevation sits
at/below a low percentile of that reservoir's OWN historical record.

HONEST BASIS (skill-spec rule 8 — no silent substitution): Puerto Rico's official
reservoir operating levels (AAA "niveles de observación / ajuste / control") are
NOT published as public per-site constants, so this does NOT claim to detect an
official drought stage. It is a *statistical, self-referential* low-supply signal
— "this reservoir is lower than it has been for all but N% of its measured
history" — clearly labelled as such in status_text and tagged T2/needs_review.
When the official levels become available, swap `_threshold` for them.

Each alert links to the reservoir's ``USGS_<site>`` utility_asset (so it joins the
asset in the federation graph) and inherits the asset's municipality/name.

Run AFTER ingest_usgs_levels (needs the readings) and ingest_usgs_water (for the
asset lookup):
    python scripts/derive_reservoir_alerts.py --percentile 10 --min-obs 30

Merges into data/service_events.jsonl, idempotent: prior derived alerts (source_ref
prefix below) are replaced; all other events preserved.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DERIVED_SOURCE_PREFIX = "AYL reservoir-alert"
# Prefer PR Datum 2002 elevation, then LMSL, then storage %, then any.
PARAM_PRIORITY = ["72379", "72375", "62615", "62614", "00054"]


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(rank)
    frac = rank - lo
    if lo + 1 >= len(sorted_vals):
        return sorted_vals[-1]
    return sorted_vals[lo] + frac * (sorted_vals[lo + 1] - sorted_vals[lo])


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _series_by_asset(readings: list[dict]) -> dict[str, dict[str, list[dict]]]:
    """asset_id -> parameter_code -> [readings] (elevation/storage metrics only)."""
    out: dict[str, dict[str, list[dict]]] = {}
    for r in readings:
        if r.get("metric") not in ("reservoir_elevation", "reservoir_storage_pct"):
            continue
        out.setdefault(r["asset_id"], {}).setdefault(r.get("parameter_code") or "", []).append(r)
    return out


def _pick_series(by_param: dict[str, list[dict]]) -> list[dict]:
    for p in PARAM_PRIORITY:
        if by_param.get(p):
            return by_param[p]
    # else the param with the most observations
    return max(by_param.values(), key=len) if by_param else []


def _asset_index(assets: list[dict]) -> dict[str, dict]:
    return {a["asset_id"]: a for a in assets if str(a.get("asset_id", "")).startswith("USGS_")}


def build_alerts(
    readings: list[dict],
    assets: list[dict],
    percentile: float,
    min_obs: int,
) -> list[dict]:
    try:
        sys.path.insert(0, str(REPO / "src"))
        from aguayluz.confidence import score

        conf = int(score("T2", has_coords=True))
    except Exception:
        conf = 60

    idx = _asset_index(assets)
    alerts: list[dict] = []
    for asset_id, by_param in _series_by_asset(readings).items():
        series = _pick_series(by_param)
        if len(series) < min_obs:
            continue
        series = sorted(series, key=lambda r: r["observed_date"])
        values = [float(r["value"]) for r in series]
        latest = series[-1]
        threshold = _percentile(sorted(values), percentile)
        if float(latest["value"]) > threshold:
            continue  # not low — no alert

        site = asset_id.removeprefix("USGS_")
        asset = idx.get(asset_id, {})
        name = asset.get("asset_name") or asset_id
        muni = asset.get("municipality") if asset.get("municipality") not in (None, "unknown") else None
        unit = latest.get("unit", "")
        day = latest["observed_date"].replace("-", "")
        alerts.append({
            "event_id": f"AYL_EVT_{day}_{site}_lowlevel",
            "event_type": "service_interruption",
            "affected_area": (muni or name),
            "municipality": muni,
            "zone": None,
            "status_text": (
                f"{name}: level {latest['value']} {unit} at/below the "
                f"{percentile:g}th-percentile ({round(threshold, 2)} {unit}) of "
                f"{len(values)} obs since {series[0]['observed_date']} "
                f"— statistical low-supply alert; NOT an official AAA operating level"
            ),
            "start_time": f"{latest['observed_date']}T00:00:00Z",
            "end_time": None,
            "reported_customers_or_users": None,
            "source_ref": (
                f"{DERIVED_SOURCE_PREFIX} p{percentile:g} over USGS NWIS levels, site {site}"
            ),
            "source_hash": None,
            "evidence_tier": "T2",
            "confidence": conf,
            "review_status": "needs_review",
            "linked_asset_ids": [asset_id],
        })
    return alerts


def merge(existing: list[dict], alerts: list[dict]) -> list[dict]:
    kept = [e for e in existing if not str(e.get("source_ref", "")).startswith(DERIVED_SOURCE_PREFIX)]
    by_id = {e["event_id"]: e for e in kept}
    for a in alerts:
        by_id[a["event_id"]] = a
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--readings", default="data/reservoir_levels.jsonl")
    ap.add_argument("--assets", default="data/utility_assets.jsonl")
    ap.add_argument("--out", default="data/service_events.jsonl")
    ap.add_argument("--percentile", type=float, default=10.0,
                    help="alert when latest level <= this percentile of the reservoir's history")
    ap.add_argument("--min-obs", type=int, default=30,
                    help="skip reservoirs with fewer than this many observations")
    args = ap.parse_args()

    readings = _read_jsonl(Path(args.readings))
    assets = _read_jsonl(Path(args.assets))
    alerts = build_alerts(readings, assets, args.percentile, args.min_obs)

    out = Path(args.out)
    combined = merge(_read_jsonl(out), alerts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))

    reservoirs = len({r["asset_id"] for r in readings
                      if r.get("metric") in ("reservoir_elevation", "reservoir_storage_pct")})
    print(f"evaluated {reservoirs} reservoir(s) at p{args.percentile:g} (min_obs={args.min_obs})")
    print(f"wrote {len(alerts)} low-level alert(s) -> {out}")
    print(f"  total events in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
