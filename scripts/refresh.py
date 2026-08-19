#!/usr/bin/env python3
"""Refresh the AguaYLuz live corpus and rebuild derived/exported outputs.

Every networked producer is explicit in ``PLANS``. New USGS modern-API vectors are
optional at runtime but are not allowed to disappear from the machine-readable
coverage matrix; ``validate_usgs_api_coverage.py`` fails closed on missing producers
or unscheduled categories.
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
_NOW_TS = "__NOW_ISO__"

STEP_NWS = ("NWS active alerts → service_events", ["scripts/ingest_nws_alerts.py"], False)
STEP_NHC = (
    "NHC Atlantic tropical cyclones → service_events",
    ["scripts/ingest_nhc_storms.py"],
    True,
)
STEP_USGS_QUAKES = (
    "USGS earthquakes → service_events",
    ["scripts/ingest_usgs_quakes.py"],
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
    "USGS groundwater daily values → groundwater_levels",
    ["scripts/ingest_usgs_groundwater.py", "--days", "365"],
    True,
)
STEP_USGS_CONTINUOUS = (
    "USGS modern continuous values → usgs_continuous_readings",
    ["scripts/ingest_usgs_continuous.py"],
    True,
)
STEP_USGS_FIELD_MEASUREMENTS = (
    "USGS OGC field measurements → usgs_field_measurements_readings",
    ["scripts/ingest_usgs_field_measurements.py"],
    True,
)
# Backward-compatible name used by the Laguna/GUI-facing refresh-plan regressions.
STEP_USGS_FIELD_MEAS = STEP_USGS_FIELD_MEASUREMENTS
STEP_USGS_PEAKS = (
    "USGS OGC annual peaks → usgs_peaks_readings",
    ["scripts/ingest_usgs_peaks.py"],
    True,
)
STEP_USGS_METADATA = (
    "USGS monitoring locations + time-series metadata registries",
    ["scripts/ingest_usgs_time_series_metadata.py"],
    True,
)
STEP_USGS_WATER_QUALITY = (
    "WQP + USGS Samples statewide discovery",
    ["scripts/ingest_usgs_water_quality.py"],
    True,
)
STEP_USGS_STATISTICS = (
    "USGS statistics baselines",
    ["scripts/ingest_usgs_statistics.py"],
    True,
)
STEP_USGS_RTFI = (
    "USGS real-time flood impacts",
    ["scripts/ingest_usgs_rtfi.py"],
    True,
)
STEP_USGS_NIMS = (
    "USGS NIMS camera metadata + image listings",
    ["scripts/ingest_usgs_nims.py"],
    True,
)
STEP_USGS_SAMPLES = (
    "USGS discrete samples (Laguna Cartagena) → usgs_samples_readings",
    ["scripts/ingest_usgs_samples.py"],
    True,
)
STEP_NOAA_TIDES = (
    "NOAA CO-OPS tides → coastal_levels",
    ["scripts/ingest_noaa_tides.py", "--days", "90"],
    True,
)
STEP_NEON = (
    "NEON D04 availability → neon_availability + utility_assets",
    ["scripts/ingest_neon.py"],
    True,
)
STEP_NEON_PRODUCTS = (
    "NEON water products → neon_readings",
    ["scripts/ingest_neon_products.py"],
    True,
)
STEP_SDWIS = (
    "EPA SDWIS violations → service_events",
    ["scripts/ingest_sdwis_violations.py"],
    False,
)
STEP_ECHO = ("EPA ECHO CWA enforcement → service_events", ["scripts/ingest_echo.py"], True)
STEP_FEMA = ("FEMA disaster declarations → service_events", ["scripts/ingest_fema.py"], True)
STEP_OSHA = (
    "OSHA enforcement → service_events",
    ["scripts/ingest_osha.py"],
    True,
)
STEP_AEE_FETCH = (
    "MiLUMA live fetch → /tmp/outages_by_town.json",
    ["scripts/fetch_luma_live.py", "--out", "/tmp/outages_by_town.json"],
    True,
)
STEP_AEE_INGEST = (
    "AEE snapshot ingest → aee_incidents",
    [
        "scripts/ingest_aee.py",
        "--src",
        "/tmp/outages_by_town.json",
        "--snapshot-ts",
        _NOW_TS,
    ],
    True,
)
STEP_WATERS_ENRICH = (
    "EPA WATERS/NHDPlus asset enrichment",
    ["scripts/enrich_waters_nhd.py"],
    True,
)
STEP_USGS_COVERAGE_GATE = (
    "USGS 10-category coverage matrix validation",
    ["scripts/validate_usgs_api_coverage.py"],
    False,
)
STEP_WATER_POWER = (
    "water↔power dependency crosswalk",
    ["scripts/build_water_power_crosswalk.py"],
    False,
)
STEP_ALERTS = (
    "signals → AlertEvents",
    ["scripts/build_alerts.py"],
    False,
)
STEP_ALERT_SYSTEM = (
    "alert system build + VAL validation",
    ["scripts/build_alert_system.py"],
    False,
)
STEP_EXPORT = (
    "federation + outputs rebuild",
    ["scripts/federation_export.py"],
    False,
)

_DERIVE = [STEP_WATER_POWER, STEP_ALERTS, STEP_ALERT_SYSTEM]

PLANS: dict[str, list[tuple]] = {
    "fast": [
        STEP_NWS,
        STEP_NHC,
        STEP_USGS_QUAKES,
        STEP_USGS_CONTINUOUS,
        STEP_USGS_RTFI,
        STEP_NOAA_TIDES,
        STEP_USGS_COVERAGE_GATE,
        *_DERIVE,
    ],
    "daily": [
        STEP_NWS,
        STEP_NHC,
        STEP_USGS_QUAKES,
        STEP_USGS_LEVELS,
        STEP_USGS_GW,
        STEP_USGS_CONTINUOUS,
        STEP_USGS_FIELD_MEASUREMENTS,
        STEP_USGS_METADATA,
        STEP_USGS_RTFI,
        STEP_USGS_NIMS,
        STEP_NOAA_TIDES,
        STEP_NEON,
        STEP_USGS_SAMPLES,
        STEP_USGS_COVERAGE_GATE,
        *_DERIVE,
    ],
    "weekly": [
        STEP_NWS,
        STEP_NHC,
        STEP_USGS_QUAKES,
        STEP_USGS_ASSETS,
        STEP_USGS_LEVELS,
        STEP_USGS_GW,
        STEP_USGS_CONTINUOUS,
        STEP_USGS_FIELD_MEASUREMENTS,
        STEP_USGS_PEAKS,
        STEP_USGS_METADATA,
        STEP_USGS_WATER_QUALITY,
        STEP_USGS_STATISTICS,
        STEP_USGS_RTFI,
        STEP_USGS_NIMS,
        STEP_NOAA_TIDES,
        STEP_NEON,
        STEP_NEON_PRODUCTS,
        STEP_USGS_SAMPLES,
        STEP_SDWIS,
        STEP_ECHO,
        STEP_FEMA,
        STEP_OSHA,
        STEP_WATERS_ENRICH,
        STEP_USGS_COVERAGE_GATE,
        *_DERIVE,
    ],
    "all": [
        STEP_NWS,
        STEP_NHC,
        STEP_USGS_QUAKES,
        STEP_USGS_ASSETS,
        STEP_USGS_LEVELS,
        STEP_USGS_GW,
        STEP_USGS_CONTINUOUS,
        STEP_USGS_FIELD_MEASUREMENTS,
        STEP_USGS_PEAKS,
        STEP_USGS_METADATA,
        STEP_USGS_WATER_QUALITY,
        STEP_USGS_STATISTICS,
        STEP_USGS_RTFI,
        STEP_USGS_NIMS,
        STEP_NOAA_TIDES,
        STEP_NEON,
        STEP_NEON_PRODUCTS,
        STEP_USGS_SAMPLES,
        STEP_SDWIS,
        STEP_ECHO,
        STEP_FEMA,
        STEP_OSHA,
        STEP_AEE_FETCH,
        STEP_AEE_INGEST,
        STEP_WATERS_ENRICH,
        STEP_USGS_COVERAGE_GATE,
        *_DERIVE,
    ],
}


def run_step(label: str, argv: list[str], dry_run: bool, optional: bool = False) -> bool:
    now_iso = datetime.now(timezone.utc).isoformat()
    argv = [now_iso if value == _NOW_TS else value for value in argv]
    printable = "python " + " ".join(argv)
    if dry_run:
        flag = "[optional] " if optional else ""
        print(f"  [dry-run] {flag}{label}: {printable}")
        return True
    print(f"\n▶ {label}\n  $ {printable}", flush=True)
    started = time.time()
    process = subprocess.run([PY, *argv], cwd=REPO)
    elapsed = f"{time.time() - started:.1f}s"
    if process.returncode == 0:
        print(f"  ✓ {label} ({elapsed})")
        return True
    if optional:
        print(f"  ⚠ {label} failed (optional; continuing) exit={process.returncode} ({elapsed})")
        return True
    print(f"  ✗ {label} ({elapsed}, exit {process.returncode})")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--fast", action="store_true")
    group.add_argument("--daily", action="store_true")
    group.add_argument("--weekly", action="store_true")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--no-export", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cadence = (
        "fast"
        if args.fast
        else "weekly"
        if args.weekly
        else "all"
        if args.all
        else "daily"
    )
    steps = list(PLANS[cadence])
    if not args.no_export:
        steps.append(STEP_EXPORT)
    print(f"AguaYLuz refresh — cadence={cadence}, {len(steps)} step(s), repo={REPO}")
    for step in steps:
        label, argv = step[0], step[1]
        optional = step[2] if len(step) > 2 else False
        if not run_step(label, argv, args.dry_run, optional=optional):
            print(f"\nFAILED at: {label} — corpus left as-is, no export.", file=sys.stderr)
            return 1
    print(f"\n✓ refresh complete ({cadence}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
