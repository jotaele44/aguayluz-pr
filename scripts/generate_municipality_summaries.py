#!/usr/bin/env python3
"""Aggregate per-municipality dossiers from current outputs/."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import OUTPUTS_DIR  # noqa: E402
from aguayluz.analysis import aggregate_by_municipality  # noqa: E402
from aguayluz.models import validate_against_schema  # noqa: E402


def _load(path: Path, default):  # type: ignore[no-untyped-def]
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Aggregate per-municipality summaries")
    p.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR)
    args = p.parse_args(argv)

    assets = _load(args.outputs_dir / "utility_assets.json", [])
    events = _load(args.outputs_dir / "service_events.json", [])
    recon = _load(args.outputs_dir / "reconciliation_report.json", {})
    findings = (recon.get("findings") or []) if isinstance(recon, dict) else []
    watersheds = _load(args.outputs_dir / "watershed_delineation.json", [])

    summaries, unattributed = aggregate_by_municipality(
        assets=assets,
        events=events,
        findings=findings,
        watersheds=watersheds,
    )

    payload = {
        "module_id": "aguayluz-pr",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "municipalities": summaries,
        "unattributed": unattributed,
    }
    validate_against_schema("municipality_summary", payload)

    (args.outputs_dir / "municipality_summaries.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    print(
        f"municipalities={len(summaries)} "
        f"top_muni={summaries[0]['municipality'] if summaries else '-'} "
        f"unattributed_assets={unattributed['asset_total']} "
        f"unattributed_events={unattributed['event_total']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
