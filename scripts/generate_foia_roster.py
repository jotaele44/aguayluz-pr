#!/usr/bin/env python3
"""Generate outputs/foia_roster.json from current outputs/ gap streams."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import CONFIG_DIR, OUTPUTS_DIR  # noqa: E402
from aguayluz.foia import generate_targets, load_agencies  # noqa: E402
from aguayluz.models import validate_against_schema  # noqa: E402


def _load(path: Path, default):  # type: ignore[no-untyped-def]
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _make_roster_id(slug: str) -> str:
    return f"AYL_FOIA_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{slug}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate FOIA roster from producer gaps")
    p.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR)
    p.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    p.add_argument("--slug", default="roster",
                   help="Slug appended to the auto-generated roster_id")
    args = p.parse_args(argv)

    review_queue = _load(args.outputs_dir / "review_queue.json", {"items": []})
    review_items = (review_queue.get("items") or []) if isinstance(review_queue, dict) else []

    recon = _load(args.outputs_dir / "reconciliation_report.json", {})
    findings = (recon.get("findings") or []) if isinstance(recon, dict) else []

    assets = _load(args.outputs_dir / "utility_assets.json", [])
    partial_assets = [a for a in assets if isinstance(a, dict) and a.get("attribute_coverage") == "partial"]

    agencies = load_agencies(args.config_dir / "foia_agencies.yaml")

    targets = generate_targets(
        review_items=review_items,
        reconciliation_findings=findings,
        partial_assets=partial_assets,
        agencies=agencies,
    )

    roster = {
        "module_id": "aguayluz-pr",
        "roster_id": _make_roster_id(args.slug),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "targets": targets,
    }
    validate_against_schema("foia_roster", roster)

    (args.outputs_dir / "foia_roster.json").write_text(
        json.dumps(roster, indent=2), encoding="utf-8"
    )

    agencies_hit = sorted({t["agency"] for t in targets})
    print(f"targets={len(targets)} agencies={agencies_hit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
