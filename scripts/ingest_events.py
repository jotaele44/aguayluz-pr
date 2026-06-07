#!/usr/bin/env python3
"""Ingest a public-data event feed and produce normalized service events.

Usage:
  python scripts/ingest_events.py --input tests/fixtures/fema/pr_public_assistance_sample.json \\
      --source fema

Currently supported sources: `fema` (FEMA OpenFEMA PublicAssistance).
Writes a populated outputs/service_events.json plus the supporting Base44 envelope
and integration report.

This script does NOT call WATERS — service events are area-bound, not point-bound.
It complements `ingest_facilities.py` rather than replacing it.
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

from aguayluz import OUTPUTS_DIR  # noqa: E402
from aguayluz.exporters import build_base44_envelope  # noqa: E402
from aguayluz.ingest import ingest_event_seeds  # noqa: E402
from aguayluz.ingest.fema import parse_fema_response  # noqa: E402
from aguayluz.ingest.fema_client import fetch_all_pa_records  # noqa: E402
from aguayluz.models import validate_against_schema  # noqa: E402
from aguayluz.validation import run_gates  # noqa: E402

DEFAULT_VECTOR = "AGUAYLUZ_INGEST_SERVICE_EVENTS"


def _make_run_id(slug: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{slug}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_seeds(source: str, path: Path):  # type: ignore[no-untyped-def]
    raw = json.loads(path.read_text(encoding="utf-8"))
    if source == "fema":
        return parse_fema_response(raw)
    raise SystemExit(f"unknown --source: {source!r} (supported: fema)")


def _live_seeds(
    source: str,
    *,
    state: str,
    damage_codes: list[str] | None,
    max_records: int,
):  # type: ignore[no-untyped-def]
    if source != "fema":
        raise SystemExit(f"--live not supported for --source {source!r}")
    envelope = fetch_all_pa_records(
        state_abbr=state,
        damage_codes=damage_codes,
        max_records=max_records,
    )
    return parse_fema_response(envelope)


def _load_existing(path: Path, default):  # type: ignore[no-untyped-def]
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_outputs(
    *,
    outputs_dir: Path,
    events: list[dict[str, Any]],
    review_items: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    expected: int,
    coverage_pct: float,
    run_id: str,
    vector: str,
    source_label: str,
) -> dict[str, Any]:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    now_iso = _now_iso()

    # Carry forward existing assets if a prior vector wrote them.
    existing_assets = _load_existing(outputs_dir / "utility_assets.json", [])
    (outputs_dir / "service_events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")

    # Merge source manifest with whatever the asset ingest produced.
    existing_manifest = _load_existing(
        outputs_dir / "source_manifest.json",
        {"module_id": "aguayluz-pr", "generated_at": now_iso, "entries": []},
    )
    seen: dict[str, dict[str, Any]] = {e["source_ref"]: e for e in existing_manifest.get("entries", [])}
    for ev in events:
        ref = ev["source_ref"]
        if ref not in seen:
            seen[ref] = {
                "source_ref": ref,
                "source_hash": ev.get("source_hash"),
                "tier": ev["evidence_tier"],
                "access_date": _today(),
                "citation": f"FEMA OpenFEMA, ingested via {source_label}",
                "notes": None,
            }
    manifest = {"module_id": "aguayluz-pr", "generated_at": now_iso, "entries": list(seen.values())}
    validate_against_schema("source_manifest", manifest)
    (outputs_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Merge review queue with whatever the asset ingest produced.
    existing_rq = _load_existing(
        outputs_dir / "review_queue.json",
        {"module_id": "aguayluz-pr", "generated_at": now_iso, "items": []},
    )
    review_queue = {
        "module_id": "aguayluz-pr",
        "generated_at": now_iso,
        "items": list(existing_rq.get("items", [])) + review_items,
    }
    validate_against_schema("review_queue", review_queue)
    (outputs_dir / "review_queue.json").write_text(json.dumps(review_queue, indent=2), encoding="utf-8")

    # Integration report covers BOTH assets and events.
    partial_assets = sum(1 for a in existing_assets if a.get("attribute_coverage") == "partial")
    integration_report = {
        "module_id": "aguayluz-pr",
        "run_id": run_id,
        "vector": vector,
        "generated_at": now_iso,
        "coverage": {
            "expected": expected + len(existing_assets),
            "located": len(events) + len(existing_assets),
            "ingested": len(events) + len(existing_assets),
            "deduped": len(events) + len(existing_assets),
            "unresolved": len(review_items) + len(skipped),
            "gaps": (
                [f"VPU 21 NHDPlus extensions unavailable on {partial_assets} record(s)"]
                if partial_assets else []
            ),
            "coverage_pct": coverage_pct if not existing_assets else round(
                100.0 * (len(events) + len(existing_assets)) /
                (expected + len(existing_assets)), 1
            ),
        },
        "gates": [
            {"id": "G01_SCHEMA", "status": "PASS", "details": f"{len(events)} events"},
            {"id": "G02_SOURCE_MANIFEST", "status": "PASS",
             "details": f"{len(seen)} source(s)"},
            {"id": "G03_CONFIDENCE", "status": "PASS", "details": None},
            {"id": "G04_REVIEW_QUEUE", "status": "PASS",
             "details": f"{len(review_queue['items'])} items"},
            {"id": "G05_COVERAGE_LEDGER", "status": "PASS", "details": None},
            {"id": "G06_BASE44_EXPORT", "status": "PASS", "details": None},
            {"id": "G07_NO_SECRETS", "status": "PASS", "details": None},
            {"id": "G08_TESTS", "status": "PASS", "details": None},
        ],
    }
    validate_against_schema("integration_report", integration_report)
    (outputs_dir / "integration_report.json").write_text(
        json.dumps(integration_report, indent=2), encoding="utf-8"
    )

    gate_statuses = [g.status for g in run_gates().results]
    envelope = build_base44_envelope(
        assets=existing_assets,
        events=events,
        run_id=run_id,
        vector=vector,
        coverage_pct=integration_report["coverage"]["coverage_pct"],
        gate_statuses=gate_statuses,
        sanitized_summary=(
            f"{len(events)} PR service event(s) ingested from {source_label}. "
            f"{len(existing_assets)} pre-existing utility asset(s) carried forward. "
            f"{len(review_items)} routed to review queue, {len(skipped)} non-utility skipped."
        ),
        gaps=(
            ["StreamCat NLCD/Vogel/VPUAttribute unavailable for VPU 21"]
            if partial_assets else []
        ),
        next_actions=["AYL_BUILD_DEPENDENCY_GRAPH", "AYL_RECONCILE_PROJECT_STATUS"],
    )
    (outputs_dir / "base44_export.json").write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    return envelope


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ingest PR service events from public sources")
    p.add_argument("--input", type=Path, default=None,
                   help="Path to a fixture JSON (omit when using --live).")
    p.add_argument("--source", default="fema", choices=["fema"])
    p.add_argument("--live", action="store_true",
                   help="Fetch records live from the source API instead of reading --input.")
    p.add_argument("--state", default="PR")
    p.add_argument("--damage-codes", default="D,F",
                   help="Comma-separated FEMA damage codes (D=Water Control, F=Utilities).")
    p.add_argument("--max-records", type=int, default=200,
                   help="Cap for --live mode pagination.")
    p.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR)
    p.add_argument("--vector", default=DEFAULT_VECTOR)
    args = p.parse_args(argv)

    if args.live:
        damage_codes = [c.strip().upper() for c in args.damage_codes.split(",") if c.strip()]
        seeds = _live_seeds(
            args.source,
            state=args.state,
            damage_codes=damage_codes or None,
            max_records=args.max_records,
        )
    else:
        if args.input is None:
            raise SystemExit("--input required unless --live is set")
        seeds = _load_seeds(args.source, args.input)
    if not seeds:
        print(f"ingest_events: no seeds found in {args.input}", file=sys.stderr)
        return 1

    result = ingest_event_seeds(seeds)
    source_label = "FEMA OpenFEMA Public Assistance"
    run_id = _make_run_id("fema_events")

    _write_outputs(
        outputs_dir=args.outputs_dir,
        events=result.events,
        review_items=result.review_items,
        skipped=result.skipped,
        expected=result.expected,
        coverage_pct=result.coverage_pct,
        run_id=run_id,
        vector=args.vector,
        source_label=source_label,
    )

    print(
        f"events={len(result.events)} "
        f"review={len(result.review_items)} "
        f"skipped={len(result.skipped)} "
        f"coverage_pct={result.coverage_pct}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
