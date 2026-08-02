#!/usr/bin/env python3
"""Assess documentation coverage per Puerto Rico reservoir/lake.

Combines the documentation axes AguaYLuz actually holds into a per-lake scorecard:

  1. USGS monitoring depth  — the authoritative record: daily water-surface
     elevation series (parm 72375 LMSL / 72379 PR Datum 2002), its span and
     observation count, and whether it is still active. Embedded below from the
     NWIS series catalog (waterservices.usgs.gov ... seriesCatalogOutput, captured
     2026-06-09); pass --usgs-rdb to refresh from a live/cached catalog.
  2. Hydro knowledge base   — mention density in the PR hydro master workbook
     (Source Inventory / Hydro Plants / Sedimentation / Gap Register sheets).
     Pass --hydro <xlsx>. Counts include river/basin references that share a name
     (e.g. Río Grande de Loíza), so treat as a documentation-density proxy.
  3. DOE/OSTI publications   — mention count across the OSTI PR-energy corpus.
     Pass --osti <csv>. Optional; skipped (marked n/a) if unreadable.

Outputs reports/lake_documentation_assessment.{md,json}. A composite tier
(High / Medium / Low / Discontinued) flags where coverage is thin so it can be
prioritized before the next ingest work.

Run: python scripts/assess_lake_documentation.py \
        --hydro ~/Documents/Data/Energy_Sector/EIA_Generator_Data/PR_Hydro_Unified_Repository_v2.xlsx \
        --osti  ~/Documents/Data/Energy_Sector/Tables_CSV/osti_pr_energy_publications.csv
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (name, usgs_site, elev_begin_year, elev_end_year, elev_obs, active) — USGS NWIS
# daily water-surface elevation series, captured from the series catalog 2026-06-09.
USGS = [
    ("Lago Loíza", "50059000", 1987, 2026, 13763, True),
    ("Lago Guayo", "50141500", 1980, 2026, 14419, True),
    ("Lago Cidra", "50047550", 1988, 2026, 13573, True),
    ("Lago La Plata", "50045000", 1989, 2026, 13494, True),
    ("Lago El Guineo", "50032290", 1988, 2026, 13326, True),
    ("Lago de Matrullas", "50032590", 1988, 2026, 12670, True),
    ("Lago Lucchetti", "50125780", 1989, 2026, 12598, True),
    ("Lago Cerrillos", "50113950", 1991, 2026, 11814, True),
    ("Lago Garzas", "50020100", 1988, 2026, 11404, True),
    ("Lago Patillas", "50093045", 1995, 2026, 11191, True),
    ("Lago Guayabal", "50111300", 1995, 2026, 11159, True),
    ("Lago Caonillas", "50026140", 1991, 2026, 11062, True),
    ("Lago Loco", "50128900", 1995, 2026, 11051, True),
    ("Lago Toa Vaca", "50111210", 1997, 2026, 10036, True),
    ("Lago Guajataca", "50010800", 1995, 2026, 10798, True),
    ("Lago Dos Bocas", "50027100", 1999, 2026, 9460, True),
    ("Lago Regulador de Isabela", "50011088", 2004, 2026, 7827, True),
    ("Lago Carite", "50039995", 2005, 2026, 7594, True),
    ("Lago Vivi", "50023110", 2004, 2026, 7461, True),
    ("Lago Coamo", "50106850", 2004, 2026, 7462, True),
    ("Lago Daguey", "50146073", 2004, 2026, 6652, True),
    ("Lago Adjuntas", "50020550", 2004, 2026, 6636, True),
    ("Lago Melania", "50095800", 2004, 2026, 6407, True),
    ("Lago Blanco", "50076800", 2010, 2026, 5770, True),
    ("Lago Fajardo", "50071225", 2011, 2026, 5084, True),
    ("Lago Portugués", "50115100", 2021, 2026, 1694, True),
    ("Lago Las Curias", "50048680", 1997, 2019, 7173, False),
    ("Lago Icacos", "50075550", 2004, 2023, 5244, False),
    ("Lago Yahuecas", "50141100", 1980, 2015, 5195, False),
    ("Lago Prieto", "50142500", 1980, 2012, 3643, False),
    ("Lago Ana María", "50112525", 2004, 2013, 2729, False),
]

# Marquee water-supply + hydro reservoirs (the water↔power keystone).
KEYSTONE = {"Lago Loíza", "Lago La Plata", "Lago Guajataca", "Lago Caonillas",
            "Lago Dos Bocas", "Lago Patillas", "Lago Guayabal", "Lago Toa Vaca",
            "Lago Cerrillos", "Lago Cidra", "Lago Carite", "Lago Lucchetti"}


def _norm(s: str) -> str:
    s = str(s).lower()
    for a, b in zip("íéáóúñ", "ieaoun"):
        s = s.replace(a, b)
    return re.sub(r"[^a-z ]", " ", s)


def _short(name: str) -> str:
    """'Lago de Matrullas' -> 'matrullas' key for mention matching."""
    k = _norm(name).replace("lago ", "").replace("de ", "").strip()
    return k


def scan_hydro(path: Path, names: list[str]) -> dict[str, int]:
    import pandas as pd

    xl = pd.ExcelFile(path)
    blob = ""
    for sh in xl.sheet_names:
        d = xl.parse(sh, header=None, dtype=str)
        blob += " " + _norm(" ".join(d.fillna("").astype(str).values.flatten()))
    return {n: blob.count(_short(n)) for n in names}


def scan_osti(path: Path, names: list[str], retries: int = 4) -> dict[str, int] | None:
    keys = {n: _short(n) for n in names}
    counts = {n: 0 for n in names}
    for _ in range(retries):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    t = _norm(line)
                    for n, k in keys.items():
                        if k in t:
                            counts[n] += 1
            return counts
        except OSError:
            time.sleep(2)
    return None


def monitoring_tier(obs: int, active: bool) -> str:
    if not active:
        return "Discontinued"
    if obs >= 10000:
        return "High"
    if obs >= 5000:
        return "Medium"
    return "Low"


def composite_tier(mon: str, hydro_hits: int | None) -> str:
    h = hydro_hits or 0
    if mon == "Discontinued":
        return "Discontinued (historical only)"
    score = {"High": 2, "Medium": 1, "Low": 0}[mon] + (2 if h >= 80 else 1 if h >= 30 else 0)
    return "High" if score >= 3 else "Medium" if score >= 1 else "Low"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hydro", type=Path, help="PR hydro master workbook (.xlsx)")
    ap.add_argument("--osti", type=Path, help="OSTI PR-energy publications CSV")
    ap.add_argument("--out-md", default=str(REPO / "reports/lake_documentation_assessment.md"))
    ap.add_argument("--out-json", default=str(REPO / "reports/lake_documentation_assessment.json"))
    args = ap.parse_args()

    names = [r[0] for r in USGS]
    hydro = scan_hydro(args.hydro, names) if args.hydro and args.hydro.is_file() else None
    osti = scan_osti(args.osti, names) if args.osti and args.osti.is_file() else None

    rows = []
    for name, site, by, ey, obs, active in USGS:
        mon = monitoring_tier(obs, active)
        h = hydro.get(name) if hydro else None
        o = osti.get(name) if osti else None
        rows.append({
            "lake": name, "usgs_site": site, "keystone": name in KEYSTONE,
            "elev_record": f"{by}–{ey}", "elev_obs": obs, "active": active,
            "monitoring_tier": mon,
            "hydro_kb_hits": h, "osti_pubs": o,
            "documentation_tier": composite_tier(mon, h),
        })
    rows.sort(key=lambda r: (not r["active"], -r["elev_obs"]))

    Path(args.out_json).write_text(json.dumps({
        "generated_note": "USGS elevation series catalog embedded (captured 2026-06-09); "
                          "hydro KB mention-density proxy; OSTI optional.",
        "hydro_scanned": hydro is not None,
        "osti_scanned": osti is not None,
        "lakes": rows,
    }, indent=2, ensure_ascii=False))

    # markdown
    L = []
    L.append("# Lake / Reservoir Documentation Assessment\n")
    L.append("_Per-reservoir documentation coverage across the sources AguaYLuz holds. "
             "Generated by `scripts/assess_lake_documentation.py`._\n")
    L.append(f"**{len(rows)} reservoirs** with USGS elevation records "
             f"({sum(r['active'] for r in rows)} active, "
             f"{sum(not r['active'] for r in rows)} discontinued).\n")
    L.append("Axes: **USGS monitoring** = daily water-surface-elevation record span + "
             "observation count (authoritative). **Hydro KB** = mention density in the PR "
             "hydro master workbook (proxy; includes same-named rivers/basins). "
             "**OSTI** = DOE publication mentions. "
             f"Hydro scanned: {'yes' if hydro else 'no'}; OSTI scanned: "
             f"{'yes' if osti else 'no (file unreadable this run)'}.\n")
    L.append("| Reservoir | Key | USGS record | Obs | Monitoring | Hydro KB | OSTI | Doc tier |")
    L.append("|---|:--:|---|--:|---|--:|--:|---|")
    for r in rows:
        L.append("| {lake} | {k} | {rec} | {obs:,} | {mon} | {h} | {o} | {doc} |".format(
            lake=r["lake"], k="★" if r["keystone"] else "",
            rec=r["elev_record"] + ("" if r["active"] else " ⛔"),
            obs=r["elev_obs"], mon=r["monitoring_tier"],
            h=r["hydro_kb_hits"] if r["hydro_kb_hits"] is not None else "n/a",
            o=r["osti_pubs"] if r["osti_pubs"] is not None else "n/a",
            doc=r["documentation_tier"]))
    L.append("\n★ = water↔power keystone reservoir (feeds both hydro generation and public supply).\n")
    # thin-coverage callout
    thin = [r["lake"] for r in rows if r["active"] and r["documentation_tier"] == "Low"]
    disc = [r["lake"] for r in rows if not r["active"]]
    L.append("## Where coverage is thin\n")
    L.append(f"- **Low documentation (active, prioritize):** {', '.join(thin) or 'none'}.")
    L.append(f"- **Discontinued monitoring (historical only — no live level signal):** "
             f"{', '.join(disc)}.")
    L.append("- **Newest dam, short record:** Lago Portugués (2021–, 1,694 obs).")
    L.append("\n> Note: hydro-KB counts for **Lago Fajardo** and **Lago Loíza** are inflated by "
             "same-named rivers (Río Fajardo, Río Grande de Loíza); treat as density, not exact.")
    Path(args.out_md).write_text("\n".join(L) + "\n")

    print(f"wrote {args.out_md}")
    print(f"wrote {args.out_json}")
    print(f"  {len(rows)} reservoirs | hydro_scanned={hydro is not None} | osti_scanned={osti is not None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
