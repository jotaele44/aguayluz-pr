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
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable

# (label, argv) — argv is relative to REPO, run with the current interpreter.
STEP_USGS_ASSETS = ("USGS site network → utility_assets", ["scripts/ingest_usgs_water.py"])
STEP_USGS_LEVELS = ("USGS daily levels → reservoir_levels", ["scripts/ingest_usgs_levels.py", "--days", "14"])
STEP_SDWIS = ("EPA SDWIS violations → service_events", ["scripts/ingest_sdwis_violations.py"])
STEP_EXPORT = ("federation + outputs rebuild", ["scripts/federation_export.py"])

PLANS = {
    "daily": [STEP_USGS_LEVELS],
    "weekly": [STEP_USGS_ASSETS, STEP_USGS_LEVELS, STEP_SDWIS],
    "all": [STEP_USGS_ASSETS, STEP_USGS_LEVELS, STEP_SDWIS],
}


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
    ap.add_argument("--no-export", action="store_true", help="skip federation/outputs rebuild")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, don't execute")
    args = ap.parse_args()

    cadence = "weekly" if args.weekly else "all" if args.all else "daily"
    steps = list(PLANS[cadence])
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
