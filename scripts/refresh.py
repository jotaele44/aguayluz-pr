#!/usr/bin/env python3
"""Refresh the AguaYLuz live data corpus, then rebuild federation + outputs.

Orchestrates the ingest scripts in dependency order and re-runs the exporter so
``data/*.jsonl`` and ``outputs/*`` stay current. Idempotent: every ingest MERGES
(USGS assets/levels by id, SDWIS by event_id), so re-runs are safe.

Cadence (each ingest hits a live federal API — run on a networked host, NOT the
sandbox, whose proxy blocks waterservices.usgs.gov / data.epa.gov):

  --daily    USGS daily reservoir levels  -> reservoir_levels.jsonl     (+ export)
             The fast-moving signal (drought / supply). ~1 call, seconds.

  --weekly   USGS site network            -> utility_assets.jsonl
             USGS daily levels            -> reservoir_levels.jsonl
             EPA SDWIS violations         -> service_events.jsonl        (+ export)
             Sites + violations change slowly; refresh weekly.

  --all      everything above, once.

Steps run as subprocesses with the SAME interpreter; the run stops at the first
failure and exits non-zero (so launchd/cron surfaces the error). --dry-run prints
the plan without executing. --no-export skips the federation/outputs rebuild.

Examples:
    python scripts/refresh.py --daily
    python scripts/refresh.py --weekly
    python scripts/refresh.py --all --dry-run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable

# (label, argv) — argv is relative to REPO, run with the current interpreter.
STEP_USGS_ASSETS = ("USGS site network → utility_assets", ["scripts/ingest_usgs_water.py"])
STEP_USGS_LEVELS = ("USGS daily levels → reservoir_levels", ["scripts/ingest_usgs_levels.py", "--days", "14"])
STEP_RES_ALERTS = ("reservoir low-level alerts → service_events", ["scripts/derive_reservoir_alerts.py"])
STEP_SDWIS = ("EPA SDWIS violations → service_events", ["scripts/ingest_sdwis_violations.py"])
STEP_RELIABILITY = ("EIA-861 SAIDI/SAIFI → reliability_readings", ["scripts/ingest_eia_reliability.py"])
STEP_OSM_POWER = ("OSM power infra → utility_assets", ["scripts/ingest_osm_power.py"])
STEP_FACILITY_FUEL = ("EIA facility-fuel → plants + generation_readings", ["scripts/ingest_eia_facility_fuel.py"])
STEP_HIFLD_POWER = ("HIFLD power infra (T1) → utility_assets", ["scripts/ingest_hifld_power.py"])
STEP_EGRID = ("EPA eGRID emissions → emissions_readings", ["scripts/ingest_egrid_emissions.py"])
STEP_DEDUP = ("cross-source power dedup → asset_crosswalk", ["scripts/dedup_power_assets.py"])
STEP_EXPORT = ("federation + outputs rebuild", ["scripts/federation_export.py"])

# reservoir alerts run right after levels (they consume the fresh readings).
# Reliability is annual (Form-861) — refresh weekly is plenty; reads the local
# Energy_Sector corpus, so it's skippable if that CSV isn't present.
PLANS = {
    "daily": [STEP_USGS_LEVELS, STEP_RES_ALERTS],
    "weekly": [STEP_USGS_ASSETS, STEP_USGS_LEVELS, STEP_RES_ALERTS, STEP_SDWIS,
               STEP_RELIABILITY, STEP_OSM_POWER, STEP_FACILITY_FUEL, STEP_HIFLD_POWER,
               STEP_EGRID, STEP_DEDUP],
    "all": [STEP_USGS_ASSETS, STEP_USGS_LEVELS, STEP_RES_ALERTS, STEP_SDWIS,
            STEP_RELIABILITY, STEP_OSM_POWER, STEP_FACILITY_FUEL, STEP_HIFLD_POWER,
            STEP_EGRID, STEP_DEDUP],
}


def luma_steps() -> list[tuple[str, list[str]]]:
    """Opt-in (--with-luma) live electric-outage pull → aee_incidents.jsonl.

    Kept OUT of the default cadences: api.miluma.lumapr.com is WAF-gated and LUMA
    has asked third parties not to republish its feed (see fetch_luma_live.py). Use
    sparingly / internally, ideally under an official data-sharing arrangement.
    """
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    tmp = "/tmp/ayl_outages_by_town.json"
    return [
        ("LUMA live outages → snapshot", ["scripts/fetch_luma_live.py", "--out", tmp]),
        ("LUMA snapshot → service_events", ["scripts/ingest_aee.py", "--src", tmp,
                                            "--snapshot-ts", ts,
                                            "--source-ref", f"MiLUMA outage API (live pull {ts})"]),
    ]


def run_step(label: str, argv: list[str], dry_run: bool) -> bool:
    cmd = [PY, *argv]
    printable = "python " + " ".join(argv)
    if dry_run:
        print(f"  [dry-run] {label}: {printable}")
        return True
    print(f"\n▶ {label}\n  $ {printable}", flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=REPO)
    ok = proc.returncode == 0
    print(f"  {'✓' if ok else '✗'} {label} ({time.time() - t0:.1f}s, exit {proc.returncode})")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--daily", action="store_true", help="USGS levels + export")
    g.add_argument("--weekly", action="store_true", help="USGS assets+levels + SDWIS + export")
    g.add_argument("--all", action="store_true", help="everything once")
    ap.add_argument("--with-luma", action="store_true",
                    help="also pull live LUMA outages (WAF/ToS-gated — see fetch_luma_live.py; use sparingly)")
    ap.add_argument("--no-export", action="store_true", help="skip federation/outputs rebuild")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, don't execute")
    args = ap.parse_args()

    cadence = "weekly" if args.weekly else "all" if args.all else "daily"
    steps = list(PLANS[cadence])
    if args.with_luma:
        steps += luma_steps()
    if not args.no_export:
        steps.append(STEP_EXPORT)

    print(f"AguaYLuz refresh — cadence={cadence}, {len(steps)} step(s), repo={REPO}")
    failures: list[str] = []
    for label, argv in steps:
        if not run_step(label, argv, args.dry_run):
            failures.append(label)
            break  # stop on first failure (don't export a half-refreshed corpus)

    if failures:
        print(f"\nFAILED at: {failures[0]} — corpus left as-is, no export.", file=sys.stderr)
        return 1
    print(f"\n✓ refresh complete ({cadence}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
