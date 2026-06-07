#!/usr/bin/env python3
"""Read entity outputs, build the Base44 envelope, write `outputs/base44_export.json`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import OUTPUTS_DIR  # noqa: E402
from aguayluz.exporters import build_base44_envelope  # noqa: E402
from aguayluz.models import validate_against_schema  # noqa: E402
from aguayluz.validation import run_gates  # noqa: E402


def _load(path: Path, default):  # type: ignore[no-untyped-def]
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _sanitized_summary(asset_count: int, partial_count: int, vector: str) -> str:
    if asset_count == 0:
        return f"No utility assets produced this run; vector={vector}."
    return (
        f"{asset_count} utility asset(s) mapped to NHDPlus V2.1 for Puerto Rico. "
        f"{partial_count} carry attribute_coverage='partial' (VPU 21 NHDPlus "
        f"Vogel/VPUAttribute/NLCD extensions unavailable per EPA inventory). "
        f"Vector: {vector}."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Base44 envelope from outputs/")
    parser.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR)
    parser.add_argument("--run-id", required=True, help="Run ID in YYYYMMDDTHHMMSSZ_slug format")
    parser.add_argument("--vector", default="AGUAYLUZ_WATER_POWER_INFRASTRUCTURE_INTELLIGENCE")
    args = parser.parse_args()

    assets = _load(args.outputs_dir / "utility_assets.json", [])
    events = _load(args.outputs_dir / "service_events.json", [])
    report = _load(args.outputs_dir / "integration_report.json", {})

    coverage_pct = float(report.get("coverage", {}).get("coverage_pct", 0.0))
    gate_statuses = [g.status for g in run_gates().results]

    partial = sum(1 for a in assets if a.get("attribute_coverage") == "partial")

    envelope = build_base44_envelope(
        assets=assets,
        events=events,
        run_id=args.run_id,
        vector=args.vector,
        coverage_pct=coverage_pct,
        gate_statuses=gate_statuses,
        sanitized_summary=_sanitized_summary(len(assets), partial, args.vector),
        gaps=(
            ["StreamCat NLCD/Vogel/VPUAttribute unavailable for VPU 21"]
            if partial > 0
            else []
        ),
        next_actions=["AYL_INGEST_PUBLIC_ASSETS", "AYL_BUILD_DEPENDENCY_GRAPH"],
    )
    validate_against_schema("base44_export", envelope)

    out = args.outputs_dir / "base44_export.json"
    out.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    print(f"wrote {out} (status={envelope['status']}, records={envelope['records_total']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
