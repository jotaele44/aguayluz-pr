#!/usr/bin/env python3
"""Export AguaYLuz water-intelligence extension streams for Federation intake."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
EXPORT = REPO / "exports" / "federation" / "water_intelligence"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + ("\n" if rows else ""), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=EXPORT)
    args = ap.parse_args()
    assets = load_jsonl(DATA / "utility_assets.jsonl")
    rels = load_jsonl(DATA / "water_relationships.jsonl")
    risks = load_jsonl(DATA / "continuity_risks.jsonl")
    water_assets = [a for a in assets if a.get("asset_type") in {"water", "wastewater"}]
    args.out.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out / "water_assets.jsonl", water_assets)
    write_jsonl(args.out / "water_relationships.jsonl", rels)
    write_jsonl(args.out / "continuity_risks.jsonl", risks)
    manifest = {
        "module": "aguayluz-pr",
        "contract": "water_intelligence_extension.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "exports": {
            "water_assets": len(water_assets),
            "water_relationships": len(rels),
            "continuity_risks": len(risks),
        },
        "paths": {
            "water_assets": "exports/federation/water_intelligence/water_assets.jsonl",
            "water_relationships": "exports/federation/water_intelligence/water_relationships.jsonl",
            "continuity_risks": "exports/federation/water_intelligence/continuity_risks.jsonl",
        },
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote water intelligence export -> {args.out}")
    print(json.dumps(manifest["exports"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
