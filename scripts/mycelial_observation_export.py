#!/usr/bin/env python3
"""Export mycelial observations and grid cells to dashboard GeoJSON and summary JSON."""
from __future__ import annotations

from mycelial_observation_common import GRID, VERIFIED, aggregate_rows, load_jsonl, parser, write_exports, write_jsonl


def main() -> int:
    args = parser(__doc__ or "export mycelial observations").parse_args()
    rows = load_jsonl(args.input or VERIFIED)
    aggregates = load_jsonl(GRID) or aggregate_rows(rows)
    if not GRID.exists():
        write_jsonl(GRID, aggregates)
    write_exports(rows, aggregates)
    print(f"exported {len(rows)} mycelial observations and {len(aggregates)} grid cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
