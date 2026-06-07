#!/usr/bin/env python3
"""Emit per-receiver federation handoff payloads.

Reads `config/federation_manifest.yaml`'s `linked_modules`, builds a tailored
`FederationHandoff` for each, writes `outputs/handoff_<target>.json`, and
updates the Base44 envelope's `federation_handoffs` pointer list.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import CONFIG_DIR, OUTPUTS_DIR  # noqa: E402
from aguayluz.exporters import build_base44_envelope, load_contradictions_from_report  # noqa: E402
from aguayluz.federation import HANDOFF_VECTOR, build_handoff_payload  # noqa: E402
from aguayluz.models import validate_against_schema  # noqa: E402
from aguayluz.validation import run_gates  # noqa: E402


def _make_run_id(slug: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{slug}"


def _load(path: Path, default):  # type: ignore[no-untyped-def]
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _load_linked_modules(manifest_path: Path) -> list[str]:
    if not manifest_path.exists():
        raise SystemExit(f"federation manifest missing: {manifest_path}")
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    modules = data.get("linked_modules") or []
    return [m for m in modules if isinstance(m, str) and m]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Emit per-receiver federation handoff payloads")
    p.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR)
    p.add_argument("--manifest", type=Path, default=CONFIG_DIR / "federation_manifest.yaml")
    p.add_argument("--vector", default=HANDOFF_VECTOR)
    p.add_argument("--confidence-floor", type=int, default=50)
    args = p.parse_args(argv)

    assets = _load(args.outputs_dir / "utility_assets.json", [])
    events = _load(args.outputs_dir / "service_events.json", [])
    findings = (_load(args.outputs_dir / "reconciliation_report.json", {}) or {}).get(
        "findings", []
    )
    watersheds = _load(args.outputs_dir / "watershed_delineation.json", [])
    bridge = _load(args.outputs_dir / "bridge_summary.json", None)

    linked = _load_linked_modules(args.manifest)
    if not linked:
        print("emit_federation_handoffs: no linked_modules in manifest", file=sys.stderr)
        return 1

    run_id = _make_run_id("handoffs")
    handoff_paths: list[dict[str, str]] = []

    for target in linked:
        payload = build_handoff_payload(
            target,
            run_id=run_id,
            assets=assets,
            events=events,
            findings=findings,
            watersheds=watersheds or None,
            bridge_summary=bridge,
            confidence_floor=args.confidence_floor,
            vector=args.vector,
        )
        validate_against_schema("federation_handoff", payload)
        relative = f"handoff_{target}.json"
        (args.outputs_dir / relative).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        handoff_paths.append({
            "target_module_id": target,
            "path": f"outputs/{relative}",
        })

    # Refresh Base44 envelope with the new federation_handoffs pointer.
    gate_statuses = [g.status for g in run_gates().results]
    coverage_pct = 100.0 if assets or events else 0.0
    envelope = build_base44_envelope(
        assets=assets,
        events=events,
        run_id=run_id,
        vector=args.vector,
        coverage_pct=coverage_pct,
        gate_statuses=gate_statuses,
        sanitized_summary=(
            f"Emitted {len(handoff_paths)} federation handoff(s): "
            + ", ".join(h["target_module_id"] for h in handoff_paths)
        ),
        contradictions=load_contradictions_from_report(
            args.outputs_dir / "reconciliation_report.json"
        ),
        federation_handoffs=handoff_paths,
        next_actions=["AYL_EXPORT_CONTROL_PLANE"],
    )
    (args.outputs_dir / "base44_export.json").write_text(
        json.dumps(envelope, indent=2), encoding="utf-8"
    )

    print(f"handoffs={len(handoff_paths)} targets={[h['target_module_id'] for h in handoff_paths]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
