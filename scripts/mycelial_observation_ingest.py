#!/usr/bin/env python3
"""Ingest a local mycelial observation JSONL file into data/mycelial/raw_observations.jsonl."""
from __future__ import annotations

from mycelial_observation_common import RAW, load_jsonl, normalize_rows, parser, write_jsonl


def main() -> int:
    args = parser(__doc__ or "ingest mycelial observations").parse_args()
    if args.input is None:
        raise SystemExit("--input is required")
    rows = normalize_rows(load_jsonl(args.input))
    write_jsonl(args.output or RAW, rows)
    print(f"wrote {len(rows)} raw mycelial observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
