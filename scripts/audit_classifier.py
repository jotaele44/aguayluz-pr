#!/usr/bin/env python3
"""Audit `infer_asset_type` against current live EPA FRS data.

What this catches: the classifier in `aguayluz.ingest.frs.infer_asset_type` is
a keyword heuristic. If EPA changes facility-naming conventions (e.g. a new
abbreviation for "wastewater treatment plant"), our utility-detect rate
drops silently and downstream entity counts shrink. The audit re-classifies
a known PR city's facilities, reports the utility-detect %, and compares
against a committed reference at `tests/baseline/classifier_rate.json`.

Modes:
  --check (default)    Run audit, compare utility_pct against the reference
                       minimum_utility_pct. Exit non-zero on drift outside
                       tolerance so the M23 oas-monitor.yml workflow alerts.
  --write-reference    Refresh the reference file with current observations.
                       Use this after manually verifying a classifier change
                       was intentional (e.g. you added Spanish keywords).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.ingest.frs import parse_frs_response  # noqa: E402
from aguayluz.ingest.frs_client import fetch_facilities  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_PATH = REPO_ROOT / "tests" / "baseline" / "classifier_rate.json"


def audit_city(*, state: str, city: str) -> dict[str, Any]:
    """Return classifier metrics for one city pull."""
    envelope = fetch_facilities(state_abbr=state, city_name=city)
    facilities = envelope.get("Results", {}).get("FRSFacility", []) or []
    if not facilities:
        return {
            "city": city,
            "total": 0,
            "utility_count": 0,
            "utility_pct": 0.0,
            "with_coords": 0,
            "without_coords": 0,
        }

    seeds = parse_frs_response(envelope)
    utility = sum(1 for s in seeds if s.is_utility)
    with_coords = sum(1 for s in seeds if s.is_utility and s.lat is not None and s.lon is not None)
    return {
        "city": city,
        "total": len(facilities),
        "utility_count": utility,
        "utility_pct": round(100.0 * utility / len(facilities), 2) if facilities else 0.0,
        "with_coords": with_coords,
        "without_coords": utility - with_coords,
    }


def evaluate(observation: dict[str, Any], reference: dict[str, Any]) -> list[str]:
    """Return a list of drift findings. Empty list = within tolerance."""
    findings: list[str] = []
    minimum = float(reference.get("minimum_utility_pct", 0.0))
    tolerance = float(reference.get("tolerance_pct_points", 0.5))
    observed = float(observation.get("utility_pct", 0.0))
    expected_ref = reference.get("reference_run") or {}
    expected_pct = float(expected_ref.get("utility_pct", minimum))

    if observed < minimum:
        findings.append(
            f"utility_pct {observed:.2f}% < minimum {minimum:.2f}% — classifier likely degraded"
        )
    if abs(observed - expected_pct) > tolerance:
        findings.append(
            f"utility_pct {observed:.2f}% drifted >{tolerance:.2f}pp from reference {expected_pct:.2f}%"
        )

    expected_total = expected_ref.get("total")
    observed_total = observation.get("total", 0)
    if expected_total and observed_total:
        delta_pct = abs(observed_total - expected_total) / expected_total * 100.0
        if delta_pct > 25.0:
            findings.append(
                f"facility_total {observed_total} drifted {delta_pct:.1f}% from reference "
                f"{expected_total} — EPA may have added/removed records for {observation.get('city')}"
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Audit FRS classifier utility-detect rate")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true",
                       help="Compare live observation against the reference (default)")
    group.add_argument("--write-reference", action="store_true",
                       help="Refresh tests/baseline/classifier_rate.json with the live observation")
    p.add_argument("--state", default="PR")
    p.add_argument("--city", default=None,
                   help="City to audit. Defaults to reference_city from the committed reference, "
                        "or BAYAMON if no reference exists.")
    p.add_argument("--minimum-pct", type=float, default=None,
                   help="Override minimum_utility_pct when writing the reference")
    p.add_argument("--tolerance-pp", type=float, default=None,
                   help="Override tolerance_pct_points when writing the reference")
    p.add_argument("--reference-path", type=Path, default=REFERENCE_PATH)
    args = p.parse_args(argv)

    reference: dict[str, Any] = {}
    if args.reference_path.exists():
        reference = json.loads(args.reference_path.read_text(encoding="utf-8"))

    city = args.city or reference.get("reference_city") or "BAYAMON"
    observation = audit_city(state=args.state, city=city)
    observation["observed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if args.write_reference:
        new_reference = {
            "_README": (
                "FRS classifier baseline. Regenerate via `python scripts/audit_classifier.py "
                "--write-reference` after manually verifying a classifier change was intentional. "
                "M23's oas-monitor.yml workflow runs --check against this file and notifies Slack "
                "on drift."
            ),
            "minimum_utility_pct": args.minimum_pct
                if args.minimum_pct is not None
                else reference.get("minimum_utility_pct", 0.5),
            "tolerance_pct_points": args.tolerance_pp
                if args.tolerance_pp is not None
                else reference.get("tolerance_pct_points", 0.5),
            "reference_city": city,
            "reference_state": args.state,
            "reference_run": {
                "total": observation["total"],
                "utility": observation["utility_count"],
                "utility_pct": observation["utility_pct"],
                "with_coords": observation["with_coords"],
                "observed_at": observation["observed_at"],
            },
        }
        args.reference_path.parent.mkdir(parents=True, exist_ok=True)
        args.reference_path.write_text(
            json.dumps(new_reference, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        try:
            display = args.reference_path.relative_to(REPO_ROOT)
        except ValueError:
            display = args.reference_path
        print(
            f"wrote {display}: {city} {observation['utility_count']}/{observation['total']} "
            f"utility ({observation['utility_pct']}%)"
        )
        return 0

    # Default: check.
    if not reference:
        print(
            f"audit_classifier: reference missing at {args.reference_path}; "
            "run --write-reference first",
            file=sys.stderr,
        )
        return 2

    findings = evaluate(observation, reference)
    print(
        f"audit: {city} {observation['utility_count']}/{observation['total']} "
        f"utility ({observation['utility_pct']}%) "
        f"vs reference minimum_pct={reference.get('minimum_utility_pct')}"
    )
    if findings:
        print("\nclassifier drift detected:", file=sys.stderr)
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("classifier rate: within tolerance ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
