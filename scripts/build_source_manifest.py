#!/usr/bin/env python3
"""Aggregate source references from `outputs/*.json` into a single manifest."""

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
from aguayluz.models import validate_against_schema  # noqa: E402

ENTITY_FILES = ("utility_assets.json", "service_events.json")


def collect_sources(outputs_dir: Path) -> list[dict[str, str | None]]:
    seen: dict[str, dict[str, str | None]] = {}
    for fname in ENTITY_FILES:
        p = outputs_dir / fname
        if not p.exists():
            continue
        for rec in json.loads(p.read_text(encoding="utf-8")):
            ref = rec.get("source_ref")
            if not ref or ref in seen:
                continue
            seen[ref] = {
                "source_ref": ref,
                "source_hash": rec.get("source_hash"),
                "tier": rec.get("evidence_tier", "T1"),
                "access_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "citation": "U.S. EPA Office of Water WATERS Services API",
                "notes": None,
            }
    return list(seen.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Build outputs/source_manifest.json")
    parser.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR)
    parser.add_argument("--generated-at", default=None, help="ISO timestamp; defaults to now")
    args = parser.parse_args()

    entries = collect_sources(args.outputs_dir)
    manifest = {
        "module_id": "aguayluz-pr",
        "generated_at": args.generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": entries,
    }
    validate_against_schema("source_manifest", manifest)

    out = args.outputs_dir / "source_manifest.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(entries)} source(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
