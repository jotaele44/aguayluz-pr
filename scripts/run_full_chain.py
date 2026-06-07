#!/usr/bin/env python3
"""Run the full M5→M15 vector chain in one command.

Demo mode (default) uses the committed fixtures and runs entirely offline.
Live mode (`--live`) hits EPA FRS, FEMA OpenFEMA, and (when EPA_WATERS_API_KEY
is set) the WATERS API. Used as a one-shot operational driver and as the
backbone of the M18 live-corpus baseline.

Output: the full outputs/ set (10 entity files), plus a `--baseline-write`
mode that updates `tests/baseline/live_corpus_summary.json` with the
producing run's headline counts.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = REPO_ROOT / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import OUTPUTS_DIR  # noqa: E402

# Default cities for the live-corpus baseline (top-5 PR by population).
DEFAULT_LIVE_CITIES = "BAYAMON,SAN_JUAN,PONCE,CAGUAS,MAYAGUEZ"
DEFAULT_DAMAGE_CODES = "D,F"
DEFAULT_MAX_FEMA_RECORDS = 50
BASELINE_PATH = REPO_ROOT / "tests" / "baseline" / "live_corpus_summary.json"


def _run(label: str, argv: list[str]) -> None:
    """Execute a child script, propagating its exit code on failure."""
    print(f"\n=== {label} ===", flush=True)
    proc = subprocess.run(argv, cwd=REPO_ROOT, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {proc.returncode}")


def _summary(outputs_dir: Path) -> dict[str, int | float]:
    """Build the headline counts for the baseline comparison."""

    def _count(name: str) -> int:
        path = outputs_dir / name
        if not path.exists():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict) and "items" in data:
            return len(data["items"])
        return 1

    base44 = json.loads((outputs_dir / "base44_export.json").read_text(encoding="utf-8"))
    return {
        "assets_total": _count("utility_assets.json"),
        "events_total": _count("service_events.json"),
        "watersheds_total": _count("watershed_delineation.json"),
        "review_queue_total": _count("review_queue.json"),
        "envelope_status": base44.get("status", "UNKNOWN"),
        "envelope_coverage_pct": float(base44.get("coverage_pct", 0.0)),
        "envelope_confidence_avg": float(base44.get("confidence_avg", 0.0)),
        "envelope_contradictions_total": len(base44.get("contradictions", [])),
        "envelope_records_total": int(base44.get("records_total", 0)),
    }


def _compare_baseline(current: dict[str, int | float], baseline: dict[str, int | float]) -> list[str]:
    """Return the list of drift findings; empty list means within tolerance."""
    findings: list[str] = []
    for field in ("assets_total", "events_total", "watersheds_total"):
        cur = float(current.get(field, 0))
        base = float(baseline.get(field, 0))
        if base == 0 and cur == 0:
            continue
        if base == 0:
            findings.append(f"{field}: baseline=0, current={cur} (new data appeared)")
            continue
        delta_pct = abs(cur - base) / base * 100.0
        if delta_pct > 10.0:
            findings.append(f"{field}: {base:.0f} → {cur:.0f} ({delta_pct:.1f}% drift)")
    if current.get("envelope_status") != baseline.get("envelope_status"):
        findings.append(
            f"envelope_status flipped: {baseline.get('envelope_status')} → "
            f"{current.get('envelope_status')}"
        )
    return findings


def _vector(name: str, live: bool, args: argparse.Namespace) -> list[str]:
    """Build the argv list for one vector script."""
    p = REPO_ROOT / "scripts" / name
    base = [sys.executable, str(p), "--outputs-dir", str(args.outputs_dir)]
    if name == "ingest_facilities.py":
        if live:
            return base + ["--source", "frs", "--live", "--state", args.state, "--cities", args.cities]
        return base + [
            "--source", "frs",
            "--input", str(REPO_ROOT / "tests" / "fixtures" / "frs" / "pr_bayamon_npdes.json"),
            "--demo-mode",
        ]
    if name == "ingest_events.py":
        if live:
            return base + [
                "--source", "fema", "--live", "--state", args.state,
                "--damage-codes", args.damage_codes,
                "--max-records", str(args.max_fema_records),
            ]
        return base + [
            "--source", "fema",
            "--input", str(REPO_ROOT / "tests" / "fixtures" / "fema" / "pr_public_assistance_sample.json"),
        ]
    if name == "build_dependency_graph.py":
        if live and args.use_waters:
            return base + ["--use-waters", "--max-traces", "5", "--distance-km", "10"]
        return base + ["--demo-mode"]
    if name == "reconcile_status.py":
        return base
    if name == "delineate_watersheds.py":
        if live and args.use_waters:
            return base + ["--max-calls", "10"]
        return base + ["--demo-mode"]
    if name == "emit_federation_handoffs.py":
        return base
    raise SystemExit(f"unknown vector script: {name}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run M5→M15 in one command")
    p.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR)
    p.add_argument("--live", action="store_true",
                   help="Hit FRS + FEMA live (and WATERS when --use-waters is set).")
    p.add_argument("--use-waters", action="store_true",
                   help="Add live WATERS calls (downstream_of + drainage delineation). "
                        "Requires EPA_WATERS_API_KEY.")
    p.add_argument("--state", default="PR")
    p.add_argument("--cities", default=DEFAULT_LIVE_CITIES,
                   help="Comma-separated PR cities for the FRS live pull.")
    p.add_argument("--damage-codes", default=DEFAULT_DAMAGE_CODES,
                   help="Comma-separated FEMA damage codes (D=Water Control, F=Utilities).")
    p.add_argument("--max-fema-records", type=int, default=DEFAULT_MAX_FEMA_RECORDS)
    p.add_argument("--baseline-write", action="store_true",
                   help="Write tests/baseline/live_corpus_summary.json with the producing run's counts.")
    p.add_argument("--baseline-check", action="store_true",
                   help="Compare producing run against the committed baseline; "
                        "exit 1 on >10%% drift or gate status flip.")
    args = p.parse_args(argv)

    if args.use_waters and not (
        os.environ.get("EPA_WATERS_API_KEY") or os.environ.get("API_DATA_GOV_KEY")
    ):
        print("run_full_chain: --use-waters requires EPA_WATERS_API_KEY", file=sys.stderr)
        return 2

    # Clean outputs/ but keep .gitkeep + history/ snapshots intact.
    for p_ in args.outputs_dir.glob("*.json"):
        p_.unlink()

    # M5 → M15 in dependency order.
    _run("M5  AYL_INGEST_PUBLIC_ASSETS",  _vector("ingest_facilities.py", args.live, args))
    _run("M6  AYL_INGEST_SERVICE_EVENTS", _vector("ingest_events.py", args.live, args))
    _run("M7  AYL_BUILD_DEPENDENCY_GRAPH", _vector("build_dependency_graph.py", args.live, args))
    _run("M8  AYL_RECONCILE_PROJECT_STATUS", _vector("reconcile_status.py", args.live, args))
    _run("M13 AYL_DELINEATE_WATERSHEDS", _vector("delineate_watersheds.py", args.live, args))
    _run("M15 AYL_EMIT_FEDERATION_HANDOFFS", _vector("emit_federation_handoffs.py", args.live, args))

    # Always finish with validate_repo so the gate report is fresh.
    _run("validate_repo", [sys.executable, str(REPO_ROOT / "scripts" / "validate_repo.py")])

    summary = _summary(args.outputs_dir)
    summary["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary["mode"] = "live" if args.live else "demo"
    summary["cities"] = args.cities if args.live else "fixture"

    print("\n=== chain summary ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    if args.baseline_write:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
        print(f"\nwrote baseline → {BASELINE_PATH.relative_to(REPO_ROOT)}")

    if args.baseline_check:
        if not BASELINE_PATH.exists():
            print(f"baseline missing: {BASELINE_PATH}", file=sys.stderr)
            return 3
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        findings = _compare_baseline(summary, baseline)
        if findings:
            print("\nbaseline drift:", file=sys.stderr)
            for f in findings:
                print(f"  - {f}", file=sys.stderr)
            return 4
        print("\nbaseline check: within tolerance ✓")

    return 0


if __name__ == "__main__":
    sys.exit(main())
