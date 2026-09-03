#!/usr/bin/env python3
"""Ingest EPA eGRID plant emissions for PR into monitoring_readings (metric=emissions).

eGRID (unlike EIA-860 annual) DOES cover Puerto Rico (subregion PRMS). Source: the
PR plant rows extracted by ``Energy_Sector/Scripts/eia_923_861_pull.py`` (URL fixed
to eGRID2023 rev2, 2026-06) → ``Tables_CSV/egrid<YYYY>_pr_plants.csv``.

Emissions are METRICS, not asset attributes (utility_asset has no field for them),
so each plant's annual CO2/NOx/SO2 → a ``monitoring_reading`` (metric=emissions),
linked to the plant asset by eGRID ORISPL == plant code (resolves to the existing
``HIFLD_PP_<code>`` or ``EIA_PLANT_<code>`` row; prefers the HIFLD canonical).

eGRID PLNT short codes used (stable, per eGRID Technical Guide):
  ORISPL plant code · PNAME name · PSTATABB state · YEAR data year
  PLCO2AN annual CO2 (short tons) · PLNOXAN annual NOx · PLSO2AN annual SO2

Run after eia_923_861_pull.py (eGRID) + the power ingests:
    python scripts/ingest_egrid_emissions.py
    python scripts/ingest_egrid_emissions.py --src /path/egrid2023_pr_plants.csv

Writes data/emissions_readings.jsonl (auto-discovered by federation_export's
data/*_readings.jsonl glob). Idempotent by reading_id. Skips cleanly if the CSV
isn't present yet.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
# default source candidates, newest eGRID year first
DEFAULT_SRCS = [
    "/Users/jotaele/Documents/Data/Energy_Sector/Tables_CSV/egrid2023_pr_plants.csv",
    "/Users/jotaele/Documents/Data/Energy_Sector/Tables_CSV/egrid2022_pr_plants.csv",
]
# (eGRID column, parameter_code, unit)
EMISSIONS = [
    ("PLCO2AN", "CO2", "short tons/year"),
    ("PLNOXAN", "NOX", "short tons/year"),
    ("PLSO2AN", "SO2", "short tons/year"),
]


def _num(raw):
    s = str(raw or "").strip().replace(",", "")
    if not s or s.upper() in ("", "NA", "N/A", "NULL"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _conf():
    try:
        sys.path.insert(0, str(REPO / "src"))
        from aguayluz.confidence import score
        return int(score("T1", has_coords=False))
    except Exception:
        return 65


def _plant_asset_index(assets_path: Path) -> dict[str, str]:
    """plant code -> existing asset_id, preferring HIFLD_PP over EIA_PLANT."""
    idx: dict[str, str] = {}
    if not assets_path.is_file():
        return idx
    for ln in assets_path.read_text().splitlines():
        if not ln.strip():
            continue
        aid = json.loads(ln).get("asset_id", "")
        for pfx in ("HIFLD_PP_", "EIA_PLANT_"):
            if aid.startswith(pfx):
                code = aid.removeprefix(pfx)
                # HIFLD wins; only set EIA if no HIFLD already recorded
                if aid.startswith("HIFLD_PP_") or code not in idx:
                    idx[code] = aid
    return idx


def _colget(row: dict, name: str):
    if name in row:
        return row[name]
    for k in row:  # case-insensitive fallback
        if k.strip().upper() == name:
            return row[k]
    return None


def build_readings(rows: list[dict], plant_idx: dict[str, str], conf: int) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        if str(_colget(r, "PSTATABB") or "").strip().upper() != "PR":
            continue
        code = str(_colget(r, "ORISPL") or "").strip()
        if not code or code.endswith(".0"):
            code = code[:-2] if code.endswith(".0") else code
        if not code:
            continue
        year = str(_colget(r, "YEAR") or "").strip()[:4]
        if len(year) != 4:
            year = "2023"  # eGRID2023 data year fallback
        asset_id = plant_idx.get(code, f"EIA_PLANT_{code}")
        for col, pcode, unit in EMISSIONS:
            val = _num(_colget(r, col))
            if val is None:
                continue
            out.append({
                "reading_id": f"AYL_RDG_{year}1231_{code}_{pcode}",
                "asset_id": asset_id,
                "site_no": code,
                "metric": "emissions",
                "parameter_code": pcode,
                "value": val,
                "unit": unit,
                "observed_date": f"{year}-12-31",
                "provisional": False,
                "source_ref": f"EPA eGRID{year} plant {code} {pcode}",
                "source_hash": None,
                "evidence_tier": "T1",
                "confidence": conf,
                "review_status": "accepted",
            })
    return out


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], new: list[dict]) -> list[dict]:
    by_id = {r["reading_id"]: r for r in existing}
    for r in new:
        by_id[r["reading_id"]] = r
    return sorted(by_id.values(), key=lambda r: (r["asset_id"], r["parameter_code"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=None, help="eGRID PR plants CSV (default: newest egrid*_pr_plants.csv)")
    ap.add_argument("--assets", default=str(DATA / "utility_assets.jsonl"))
    ap.add_argument("--out", default=str(DATA / "emissions_readings.jsonl"))
    args = ap.parse_args()

    src = None
    for cand in ([args.src] if args.src else DEFAULT_SRCS):
        if cand and Path(cand).is_file():
            src = Path(cand)
            break
    if src is None:
        print("eGRID PR source absent; run `eia_923_861_pull.py` (eGRID) first. Skipping.")
        return 0

    rows = _read_csv(src)
    plant_idx = _plant_asset_index(Path(args.assets))
    readings = build_readings(rows, plant_idx, _conf())
    if not readings:
        print(f"no PR emissions rows in {src.name} (check ORISPL/PSTATABB/PLCO2AN cols). Skipping.")
        return 0

    out = Path(args.out)
    combined = merge(_read_jsonl(out), readings)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))
    plants = len({r["asset_id"] for r in readings})
    print(f"wrote {len(readings)} emissions readings for {plants} plants -> {out.name}  (src: {src.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
