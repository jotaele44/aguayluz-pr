#!/usr/bin/env python3
"""Normalize raw mycelial observation rows into canonical JSONL."""
from __future__ import annotations

from mycelial_observation_common import NORMALIZED, RAW, load_jsonl, normalize_rows, parser, write_jsonl


def main() -> int:
    args = parser(__doc__ or "normalize mycelial observations").parse_args()
    rows = normalize_rows(load_jsonl(args.input or RAW))
    write_jsonl(args.output or NORMALIZED, rows)
    print(f"wrote {len(rows)} normalized mycelial observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
