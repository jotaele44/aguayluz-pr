#!/usr/bin/env python3
"""Refresh the AguaYLuz live data corpus, then rebuild federation + outputs.

Orchestrates the ingest scripts in dependency order and re-runs the exporter so
``data/*.jsonl`` and ``outputs/*`` stay current. Idempotent: every ingest MERGES
(USGS assets/levels by id, SDWIS/ECHO/FEMA/NWS by event_id), so re-runs are safe.

Cadence (each ingest hits a live federal API — run on a networked host, NOT the
sandbox, whose proxy may block waterservices.usgs.gov / data.epa.gov):

  --daily    NWS active alerts             -> service_events.jsonl
             USGS earthquakes (PR region)  -> service_events.jsonl
             USGS daily reservoir levels   -> reservoir_levels.jsonl     (+ export)
             The fast-moving signals (weather hazards, seismic, drought/supply). Seconds.

  --weekly   NWS active alerts             -> service_events.jsonl
             USGS earthquakes (PR region)  -> service_events.jsonl
             USGS site network             -> utility_assets.jsonl
             USGS daily levels             -> reservoir_levels.jsonl
             EPA SDWIS violations          -> service_events.jsonl
             EPA ECHO CWA enforcement      -> service_events.jsonl   (optional)
             FEMA disaster declarations    -> service_events.jsonl   (optional, + export)
             Sites + violations change slowly; refresh weekly. ECHO and FEMA are
             best-effort: their public REST endpoints (echo.epa.gov CWA services,
             fema.gov open/v2) currently return HTTP 404 upstream, so the run
             warns-and-continues past them (like the WAF-gated MiLUMA step) rather
             than aborting before USGS/SDWIS land and the federation export runs.

  --all      everything above, plus MiLUMA live outages (optional — WAF may block;
             warns and continues rather than failing). Requires a permissioned
             network path to api.miluma.lumapr.com (Incapsula-gated).

Steps run as subprocesses with the SAME interpreter; unless a step is marked
optional, the run stops at the first failure and exits non-zero. --dry-run prints
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

# Sentinel replaced at execution time with the current UTC ISO timestamp.
_NOW_TS = "__NOW_ISO__"

# Step tuples: (label, argv, optional=False)
# optional=True: warn and continue on failure rather than aborting the chain.
STEP_NWS = (
    "NWS active alerts → service_events",
    ["scripts/ingest_nws_alerts.py"],
    False,
)
STEP_USGS_ASSETS = (
    "USGS site network → utility_assets",
    ["scripts/ingest_usgs_water.py"],
    False,
)
STEP_USGS_LEVELS = (
    "USGS daily levels → reservoir_levels",
    ["scripts/ingest_usgs_levels.py", "--days", "14"],
    False,
)
STEP_USGS_QUAKES = (
    "USGS earthquakes → service_events",
    ["scripts/ingest_usgs_quakes.py"],
    False,
)
STEP_SDWIS = (
    "EPA SDWIS violations → service_events",
    ["scripts/ingest_sdwis_violations.py"],
    False,
)
STEP_ECHO = (
    "EPA ECHO CWA enforcement → service_events",
    ["scripts/ingest_echo.py"],
    True,   # optional — best-effort; echo.epa.gov CWA REST endpoint currently 404s
)
STEP_FEMA = (
    "FEMA disaster declarations → service_events",
    ["scripts/ingest_fema.py"],
    True,   # optional — best-effort; fema.gov open/v2 endpoint currently 404s
)
STEP_AEE_FETCH = (
    "MiLUMA live fetch → /tmp/outages_by_town.json",
    ["scripts/fetch_luma_live.py", "--out", "/tmp/outages_by_town.json"],
    True,   # optional — Incapsula WAF may return 403
)
STEP_AEE_INGEST = (
    "AEE snapshot ingest → aee_incidents",
    [
        "scripts/ingest_aee.py",
        "--src", "/tmp/outages_by_town.json",
        "--snapshot-ts", _NOW_TS,   # replaced at execution time
    ],
    True,   # optional — only runs if fetch succeeded
)
STEP_EXPORT = (
    "federation + outputs rebuild",
    ["scripts/federation_export.py"],
    False,
)

PLANS: dict[str, list[tuple]] = {
    "daily": [STEP_NWS, STEP_USGS_QUAKES, STEP_USGS_LEVELS],
    "weekly": [STEP_NWS, STEP_USGS_QUAKES, STEP_USGS_ASSETS, STEP_USGS_LEVELS, STEP_SDWIS,
               STEP_ECHO, STEP_FEMA],
    "all":   [STEP_NWS, STEP_USGS_QUAKES, STEP_USGS_ASSETS, STEP_USGS_LEVELS, STEP_SDWIS,
              STEP_ECHO, STEP_FEMA, STEP_AEE_FETCH, STEP_AEE_INGEST],
}


def run_step(label: str, argv: list[str], dry_run: bool, optional: bool = False) -> bool:
    now_iso = datetime.now(timezone.utc).isoformat()
    argv = [now_iso if a == _NOW_TS else a for a in argv]
    cmd = [PY, *argv]
    printable = "python " + " ".join(argv)
    if dry_run:
        flag = "[optional]" if optional else ""
        print(f"  [dry-run] {flag} {label}: {printable}")
        return True
    print(f"\n▶ {label}\n  $ {printable}", flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=REPO)
    ok = proc.returncode == 0
    elapsed = f"{time.time() - t0:.1f}s"
    if ok:
        print(f"  ✓ {label} ({elapsed})")
    elif optional:
        print(f"  ⚠ {label} failed (optional; continuing) exit={proc.returncode} ({elapsed})")
        return True
    else:
        print(f"  ✗ {label} ({elapsed}, exit {proc.returncode})")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--daily", action="store_true",
                   help="NWS alerts + USGS levels + export")
    g.add_argument("--weekly", action="store_true",
                   help="NWS + USGS + SDWIS + ECHO + FEMA + export")
    g.add_argument("--all", action="store_true",
                   help="everything including MiLUMA (optional, WAF-gated)")
    ap.add_argument("--no-export", action="store_true",
                    help="skip federation/outputs rebuild")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan, don't execute")
    args = ap.parse_args()

    cadence = "weekly" if args.weekly else "all" if args.all else "daily"
    steps = list(PLANS[cadence])
    if not args.no_export:
        steps.append(STEP_EXPORT)

    step_count = len(steps)
    print(f"AguaYLuz refresh — cadence={cadence}, {step_count} step(s), repo={REPO}")
    failures: list[str] = []
    for step in steps:
        label, argv = step[0], step[1]
        optional = step[2] if len(step) > 2 else False
        if not run_step(label, argv, args.dry_run, optional=optional):
            failures.append(label)
            break  # stop on non-optional failure

    if failures:
        print(f"\nFAILED at: {failures[0]} — corpus left as-is, no export.", file=sys.stderr)
        return 1
    print(f"\n✓ refresh complete ({cadence}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
