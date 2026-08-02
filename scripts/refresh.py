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
             NEON D04 availability delta   -> neon_availability.jsonl    (optional)
             The fast-moving signals (weather hazards, seismic, drought/supply). Seconds.
             NEON publishes monthly, so a daily poll is ample and costs 4 keyless
             requests against a 200/hour quota.

  --weekly   NWS active alerts             -> service_events.jsonl
             USGS earthquakes (PR region)  -> service_events.jsonl
             USGS site network             -> utility_assets.jsonl
             USGS daily levels             -> reservoir_levels.jsonl
             EPA SDWIS violations          -> service_events.jsonl
             EPA ECHO CWA enforcement      -> service_events.jsonl   (optional)
             FEMA disaster declarations    -> service_events.jsonl   (optional, + export)
             NEON water products           -> neon_readings.jsonl (optional, token)
             USGS discrete samples         -> usgs_samples_readings.jsonl (optional)
                 Archival water chemistry for the Laguna Cartagena basin, which has no
                 daily-values record at all; see docs/LAGUNA_CARTAGENA_GAP.md. Runs on
                 every cadence so the reading artifact is present as often as the others.
             EPA WATERS/NHDPlus enrichment -> utility_assets.jsonl (optional)
             Sites + violations change slowly; refresh weekly. ECHO and FEMA are
             best-effort: their public REST endpoints (echo.epa.gov CWA services,
             fema.gov open/v2) currently return HTTP 404 upstream, so the run
             warns-and-continues past them (like the WAF-gated MiLUMA step) rather
             than aborting before USGS/SDWIS land and the federation export runs.
             The WATERS enricher is optional for the same reason: it needs
             EPA_WATERS_API_KEY, which most runs do not carry. The NEON product
             download is optional on the same grounds: NEON's /api/v0/data endpoint
             returns 403 without NEON_API_TOKEN, so the step prints a skip notice and
             exits 0 rather than failing the run. NEON *availability* tracking needs
             no credential and runs daily.

Every cadence then runs the derived layers before export: the water<->power
crosswalk, alert promotion (build_alerts.py), and the alert-system build
(build_alert_system.py — JSON-Schema load, VAL-001..010 acceptance rules, and
outputs/alert_events.geojson for the dashboard's alert map layer).

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
STEP_USGS_GW = (
    "USGS groundwater → groundwater_levels",
    ["scripts/ingest_usgs_groundwater.py", "--days", "365"],
    True,   # optional — network feed; a failure must not abort the refresh
)
STEP_NOAA_TIDES = (
    "NOAA CO-OPS tides → coastal_levels",
    ["scripts/ingest_noaa_tides.py", "--days", "90"],
    True,   # optional — near-real-time coastal surge signal
)
STEP_NEON = (
    "NEON D04 availability → neon_availability + utility_assets",
    ["scripts/ingest_neon.py"],
    True,   # optional — network feed; keyless, but must not abort the refresh
)
STEP_USGS_SAMPLES = (
    "USGS discrete samples (Laguna Cartagena basin) → usgs_samples_readings",
    ["scripts/ingest_usgs_samples.py"],
    True,   # optional — network feed; keyless, but must not abort the refresh
)
# Runs in EVERY cadence, not just weekly, despite being archival data that does not
# change. data/usgs_samples_readings.jsonl is gitignored like every other reading file,
# so it exists only for the life of the job that produced it. The sibling reading
# vectors (reservoir, groundwater, coastal) are all refreshed daily, so their artifacts
# are always present; a weekly-only producer would leave this one absent on six days in
# seven. One small request is cheaper than that inconsistency.
STEP_NEON_PRODUCTS = (
    "NEON water products → neon_readings (needs NEON_API_TOKEN)",
    ["scripts/ingest_neon_products.py"],
    True,   # optional — /api/v0/data is token-gated; exits 0 and skips when unset
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
    True,   # optional — best-effort; endpoint live again at echodata.epa.gov
)
STEP_FEMA = (
    "FEMA disaster declarations → service_events",
    ["scripts/ingest_fema.py"],
    True,   # optional — best-effort; endpoint live (case-sensitive entity name)
)
STEP_OSHA = (
    "OSHA enforcement → service_events (INDUSTRIAL)",
    ["scripts/ingest_osha.py"],
    True,   # optional — best-effort; DOL v4 needs OSHA_API_KEY, absent in most runs
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
# Derived analytic layers — run after ingests, before export. They read the
# freshly-ingested corpus (service_events, reservoir_levels, utility_assets) and
# write the alert/dependency layers the exporter projects into canonical streams.
STEP_ALERTS = (
    "signals → AlertEvents (CONTAMINATION/HYDRO_OPS/SEISMIC_GEO/WEATHER_HAZARD)",
    ["scripts/build_alerts.py"],
    False,
)
STEP_WATER_POWER = (
    "water↔power dependency crosswalk (GAP-003)",
    ["scripts/build_water_power_crosswalk.py"],
    False,
)
STEP_ALERT_SYSTEM = (
    "alert system build + VAL-001..010 validation → outputs/alert_events.geojson",
    ["scripts/build_alert_system.py"],
    False,   # a schema-invalid alert must fail here, not at federation export
)
STEP_WATERS_ENRICH = (
    "EPA WATERS/NHDPlus asset enrichment",
    ["scripts/enrich_waters_nhd.py"],
    True,    # optional — needs EPA_WATERS_API_KEY, absent in most runs
)
STEP_EXPORT = (
    "federation + outputs rebuild",
    ["scripts/federation_export.py"],
    False,
)

# The derived-layer steps every cadence runs before export, in dependency order:
# crosswalk (water↔power edges) → build_alerts.py (promotes the freshly-ingested
# service_events/readings across every domain — water, seismic, weather — into the
# alert layer the exporter projects) → build_alert_system.py (loads that layer against
# its JSON Schemas, runs the VAL-001..010 acceptance pipeline, and emits
# outputs/alert_events.geojson, the dashboard's alert map layer).
#
# NOTE: scripts/build_water_alerts.py is NOT in any cadence — build_alerts.py
# generalises it by running the full aguayluz.alert_promotion registry (which includes
# the water promoters). The older script stays for direct water-only invocation.
_DERIVE = [STEP_WATER_POWER, STEP_ALERTS, STEP_ALERT_SYSTEM]

PLANS: dict[str, list[tuple]] = {
    # fast: the near-real-time hazard feeds only (seismic + NWS) + alert promotion +
    # export. Meant for a ~15-minute cron so a quake / hurricane warning becomes a
    # pushed alert in minutes, not the next daily batch.
    "fast": [STEP_NWS, STEP_USGS_QUAKES, STEP_NOAA_TIDES, *_DERIVE],
    "daily": [STEP_NWS, STEP_USGS_QUAKES, STEP_USGS_LEVELS, STEP_USGS_GW, STEP_NOAA_TIDES,
              STEP_NEON, STEP_USGS_SAMPLES, *_DERIVE],
    "weekly": [STEP_NWS, STEP_USGS_QUAKES, STEP_USGS_ASSETS, STEP_USGS_LEVELS, STEP_USGS_GW,
               STEP_NOAA_TIDES, STEP_NEON, STEP_NEON_PRODUCTS, STEP_USGS_SAMPLES,
               STEP_SDWIS, STEP_ECHO, STEP_FEMA, STEP_OSHA, STEP_WATERS_ENRICH, *_DERIVE],
    "all":   [STEP_NWS, STEP_USGS_QUAKES, STEP_USGS_ASSETS, STEP_USGS_LEVELS, STEP_USGS_GW,
              STEP_NOAA_TIDES, STEP_NEON, STEP_NEON_PRODUCTS, STEP_USGS_SAMPLES,
              STEP_SDWIS, STEP_ECHO, STEP_FEMA, STEP_OSHA, STEP_AEE_FETCH,
              STEP_AEE_INGEST, STEP_WATERS_ENRICH, *_DERIVE],
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
    g.add_argument("--fast", action="store_true",
                   help="near-real-time hazard feeds only (NWS + USGS quakes) + alerts + export")
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

    cadence = ("fast" if args.fast else "weekly" if args.weekly
               else "all" if args.all else "daily")
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
