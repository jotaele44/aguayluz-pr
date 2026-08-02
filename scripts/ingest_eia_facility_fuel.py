#!/usr/bin/env python3
"""Ingest EIA facility-fuel (Form-923) PR plants into utility_assets + generation readings.

The authoritative (T1) power-generation layer. Source: the EIA API v2
``electricity/facility-fuel`` monthly extract already pulled to the Energy_Sector
corpus as ``eia_api_pr_facility_fuel_monthly.csv`` — every PR power plant's monthly
net generation by fuel and prime mover (Central San Juan, Aguirre, EcoEléctrica,
AES, Costa Sur, plus the solar/wind farms).

Two outputs:
  * one ``utility_asset`` per plant (asset_type=power, subtype="generation (<primary
    fuel>)"), id ``EIA_PLANT_<plantCode>``. T1/accepted. NOTE: facility-fuel carries
    NO coordinates, so these are geometry_type=unknown / no lat-lon — they are the
    authoritative *record*; the OSM layer (OSMP_*) carries the geometry. Linking the
    two by name/proximity is a future dedup step (see remaining_work_queue.md).
  * one ``monitoring_reading`` per plant-month (metric=generation, MWh) from the
    plant TOTAL rows (fuel2002=ALL, primeMover=ALL) → data/generation_readings.jsonl,
    which federation_export now auto-discovers (data/*_readings.jsonl).

Run (reads the machine-local corpus; --src to override):
    python scripts/ingest_eia_facility_fuel.py \
        --src ~/Documents/Data/Energy_Sector/Tables_CSV/eia_api_pr_facility_fuel_monthly.csv

Idempotent: utility_assets merge replaces EIA_PLANT_* (preserving others); readings
merge by reading_id.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SRC = "/Users/jotaele/Documents/Data/Energy_Sector/Tables_CSV/eia_api_pr_facility_fuel_monthly.csv"
ASSET_PREFIX = "EIA_PLANT_"


def _num(raw) -> float | None:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _conf(has_coords: bool) -> int:
    try:
        sys.path.insert(0, str(REPO / "src"))
        from aguayluz.confidence import score
        return int(score("T1", has_coords=has_coords))
    except Exception:
        return 80 - (0 if has_coords else 15)


def parse(path: Path) -> tuple[list[dict], list[dict]]:
    """Return (utility_assets, generation_readings)."""
    # per plant: name, fuel→total generation (for primary fuel), monthly totals
    plants: dict[str, dict] = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            if (row.get("state") or "").strip().upper() != "PR":
                continue
            code = (row.get("plantCode") or "").strip()
            if not code:
                continue
            p = plants.setdefault(code, {
                "name": (row.get("plantName") or f"Plant {code}").strip(),
                "fuel_gen": {}, "months": {},
            })
            gen = _num(row.get("generation"))
            fuel = (row.get("fuelTypeDescription") or "").strip()
            pm = (row.get("primeMover") or "").strip().upper()
            f2 = (row.get("fuel2002") or "").strip().upper()
            period = (row.get("period") or "").strip()
            if f2 == "ALL" and pm == "ALL":
                # plant total for the month
                if gen is not None and len(period) == 7:
                    p["months"][period] = gen
            elif fuel and fuel != "Total" and gen is not None:
                p["fuel_gen"][fuel] = p["fuel_gen"].get(fuel, 0.0) + gen

    read_conf = _conf(has_coords=False)
    assets: list[dict] = []
    readings: list[dict] = []
    for code, p in plants.items():
        primary = max(p["fuel_gen"], key=p["fuel_gen"].get) if p["fuel_gen"] else "unknown"
        assets.append({
            "asset_id": f"{ASSET_PREFIX}{code}",
            "asset_name": p["name"],
            "asset_type": "power",
            "asset_subtype": f"generation ({primary})",
            "operator": None,
            "municipality": "unknown",
            "geometry_type": "unknown",
            "status": "active",
            "source_ref": f"EIA Form-923 facility-fuel (API v2), plant {code}",
            "evidence_tier": "T1",
            "confidence": _conf(has_coords=False),
            "review_status": "accepted",
        })
        for period, gen in p["months"].items():
            day = period.replace("-", "") + "01"
            readings.append({
                "reading_id": f"AYL_RDG_{day}_{code}_netgen",
                "asset_id": f"{ASSET_PREFIX}{code}",
                "site_no": code,
                "metric": "generation",
                "parameter_code": "net_generation",
                "value": gen,
                "unit": "MWh",
                "observed_date": f"{period}-01",
                "provisional": False,
                "source_ref": f"EIA Form-923 facility-fuel, plant {code} {period}",
                "source_hash": None,
                "evidence_tier": "T1",
                "confidence": read_conf,
                "review_status": "accepted",
            })
    return assets, readings


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge_assets(existing: list[dict], new: list[dict]) -> list[dict]:
    by_id = {r["asset_id"]: r for r in existing if not str(r.get("asset_id", "")).startswith(ASSET_PREFIX)}
    for r in new:
        by_id[r["asset_id"]] = r
    return list(by_id.values())


def merge_readings(existing: list[dict], new: list[dict]) -> list[dict]:
    by_id = {r["reading_id"]: r for r in existing}
    for r in new:
        by_id[r["reading_id"]] = r
    return sorted(by_id.values(), key=lambda r: (r["asset_id"], r["observed_date"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--assets-out", default="data/utility_assets.jsonl")
    ap.add_argument("--readings-out", default="data/generation_readings.jsonl")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_file():
        print(f"facility-fuel source absent ({src}); skipping (run eia_api_pr_pull.py to enable)")
        return 0
    assets, readings = parse(src)

    ap_out = Path(args.assets_out)
    ap_out.write_text("".join(json.dumps(r) + "\n" for r in merge_assets(_read_jsonl(ap_out), assets)))
    rd_out = Path(args.readings_out)
    rd_out.parent.mkdir(parents=True, exist_ok=True)
    rd_out.write_text("".join(json.dumps(r) + "\n" for r in merge_readings(_read_jsonl(rd_out), readings)))

    months = sorted({r["observed_date"][:7] for r in readings})
    print(f"wrote {len(assets)} EIA plants, {len(readings)} monthly generation readings")
    print(f"  span: {months[0]}–{months[-1]}" if months else "  no readings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
