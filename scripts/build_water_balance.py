#!/usr/bin/env python3
"""Build fail-closed water-balance intervals from monitoring readings.

The builder requires an explicit role map. It will not infer inflow, outflow or
storage roles from AguaYLuz metric names alone.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz.water_balance import build_balance_intervals  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--readings", nargs="+", type=Path, required=True)
    ap.add_argument("--role-map", type=Path, required=True)
    ap.add_argument("--interval-start", required=True)
    ap.add_argument("--interval-end", required=True)
    ap.add_argument("--out", type=Path, default=Path("data/water_balance_intervals.jsonl"))
    ap.add_argument("--quarantine-out", type=Path, default=Path("data/water_balance_quarantine.jsonl"))
    ap.add_argument("--allow-fixtures", action="store_true")
    args = ap.parse_args()

    readings: list[dict] = []
    for path in args.readings:
        readings.extend(read_jsonl(path))
    role_map = json.loads(args.role_map.read_text(encoding="utf-8"))
    intervals, quarantines = build_balance_intervals(
        readings,
        role_map,
        interval_start=args.interval_start,
        interval_end=args.interval_end,
        production_mode=not args.allow_fixtures,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.quarantine_out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in intervals), encoding="utf-8")
    args.quarantine_out.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in quarantines),
        encoding="utf-8",
    )

    print(f"wrote {len(intervals)} intervals -> {args.out}")
    print(f"wrote {len(quarantines)} quarantines -> {args.quarantine_out}")
    return 1 if any(row["balance_status"] == "blocked" for row in intervals) else 0


if __name__ == "__main__":
    raise SystemExit(main())
