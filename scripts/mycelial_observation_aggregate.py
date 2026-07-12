#!/usr/bin/env python3
"""Aggregate verified mycelial observations into map grid cells."""
from __future__ import annotations

from mycelial_observation_common import GRID, VERIFIED, aggregate_rows, load_jsonl, parser, write_jsonl


def main() -> int:
    args = parser(__doc__ or "aggregate mycelial observations").parse_args()
    rows = aggregate_rows(load_jsonl(args.input or VERIFIED))
    write_jsonl(args.output or GRID, rows)
    print(f"wrote {len(rows)} mycelial grid cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
