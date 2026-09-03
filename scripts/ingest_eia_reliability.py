#!/usr/bin/env python3
"""Ingest PR electric-utility reliability (SAIDI/SAIFI/CAIDI) into monitoring_readings.

The power-sector time-series counterpart to USGS reservoir levels. Source: EIA
Form-861 annual reliability (already pulled to the Energy_Sector corpus as
``eia861_pr_reliability.csv``), which reports each PR utility's SAIDI (avg outage
minutes/customer/yr), SAIFI (avg interruptions/customer/yr) and CAIDI
(minutes/interruption), With- and Without- Major Event Days (MED).

These are annual *metrics*, not discrete events — so they belong in
``monitoring_reading`` (metric=reliability), NOT ``service_event``. Each utility
also gets a system-level ``utility_asset`` (asset_subtype=utility_system) so the
readings have an asset to link to (the utility itself, not a point on the map).

  reading_id   AYL_RDG_<YYYY>1231_<utilityNo>_<paramcode>
  parameter    SAIDI_woMED / SAIFI_woMED / CAIDI_woMED / *_wMED
  asset_id     EIA_UTIL_<utilityNo>   (e.g. EIA_UTIL_15497 = PREPA)

Run (reads the machine-local corpus; --src to point at the CSV):
    python scripts/ingest_eia_reliability.py \
        --src ~/Documents/Data/Energy_Sector/Tables_CSV/eia861_pr_reliability.csv

Writes:
  data/utility_assets.jsonl      (+ one utility_system asset per utility; merge)
  data/reliability_readings.jsonl (monitoring_reading rows; merge by reading_id)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SRC = "/Users/jotaele/Documents/Data/Energy_Sector/Tables_CSV/eia861_pr_reliability.csv"
ASSET_PREFIX = "EIA_UTIL_"

# (csv column, parameter_code, unit) — "Without MED" is the more complete series;
# "With MED" included when present.
METRICS = [
    ("SAIDI Without MED", "SAIDI_woMED", "minutes/year"),
    ("SAIFI Without MED", "SAIFI_woMED", "interruptions/year"),
    ("CAIDI Without MED", "CAIDI_woMED", "minutes/interruption"),
    ("SAIDI With MED", "SAIDI_wMED", "minutes/year"),
    ("SAIFI With MED", "SAIFI_wMED", "interruptions/year"),
    ("CAIDI With MED", "CAIDI_wMED", "minutes/interruption"),
]


def _num(raw: Any) -> float | None:
    s = str(raw or "").strip()
    if not s or s in (".", "NA", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _conf(tier: str) -> int:
    try:
        sys.path.insert(0, str(REPO / "src"))
        from aguayluz.confidence import score
        return int(score(tier, has_coords=tier != "T1"))
    except Exception:
        return {"T1": 80, "T2": 60}.get(tier, 60)


def parse_rows(path: Path) -> tuple[list[dict], list[dict]]:
    """Return (utility_assets, reliability_readings)."""
    assets: dict[str, dict] = {}
    readings: list[dict] = []
    asset_conf = _conf("T1")
    read_conf = _conf("T1")
    with open(path, encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            if (row.get("State") or "").strip().upper() != "PR":
                continue
            try:
                year = int(float(row.get("Data Year")))
                util_no = int(float(row.get("Utility Number")))
            except (TypeError, ValueError):
                continue
            util_name = (row.get("Utility Name") or f"Utility {util_no}").strip()
            asset_id = f"{ASSET_PREFIX}{util_no}"
            assets.setdefault(asset_id, {
                "asset_id": asset_id,
                "asset_name": util_name,
                "asset_type": "power",
                "asset_subtype": "utility_system",
                "operator": util_name,
                "municipality": "unknown",
                "geometry_type": "unknown",
                "status": "active",
                "source_ref": "EIA Form-861 (reliability) — PR electric utility",
                "evidence_tier": "T1",
                "confidence": asset_conf,
                "review_status": "accepted",
            })
            for col, pcode, unit in METRICS:
                val = _num(row.get(col))
                if val is None:
                    continue
                readings.append({
                    "reading_id": f"AYL_RDG_{year}1231_{util_no}_{pcode}",
                    "asset_id": asset_id,
                    "site_no": str(util_no),
                    "metric": "reliability",
                    "parameter_code": pcode,
                    "value": val,
                    "unit": unit,
                    "observed_date": f"{year}-12-31",
                    "provisional": "Early release" in (row.get("Unnamed: 0") or ""),
                    "source_ref": f"EIA Form-861 reliability, utility {util_no} {year} {pcode}",
                    "source_hash": None,
                    "evidence_tier": "T1",
                    "confidence": read_conf,
                    "review_status": "accepted",
                })
    return list(assets.values()), readings


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
    return sorted(by_id.values(), key=lambda r: (r["asset_id"], r["parameter_code"], r["observed_date"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--assets-out", default="data/utility_assets.jsonl")
    ap.add_argument("--readings-out", default="data/reliability_readings.jsonl")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_file():
        # Optional local corpus — skip cleanly so a scheduled refresh isn't broken
        # on hosts without the Energy_Sector data.
        print(f"reliability source absent ({src}); skipping (run the Form-861 pull to enable)")
        return 0
    assets, readings = parse_rows(src)

    ap_out = Path(args.assets_out)
    ap_out.write_text("".join(json.dumps(r) + "\n" for r in merge_assets(_read_jsonl(ap_out), assets)))
    rd_out = Path(args.readings_out)
    rd_out.parent.mkdir(parents=True, exist_ok=True)
    rd_out.write_text("".join(json.dumps(r) + "\n" for r in merge_readings(_read_jsonl(rd_out), readings)))

    utils = sorted({r["asset_id"] for r in readings})
    years = sorted({r["observed_date"][:4] for r in readings})
    print(f"wrote {len(assets)} utility_system asset(s), {len(readings)} reliability readings")
    print(f"  utilities: {utils}")
    print(f"  years: {years[0]}–{years[-1]}" if years else "  no readings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
