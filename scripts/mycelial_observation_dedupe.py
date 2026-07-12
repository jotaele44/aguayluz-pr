#!/usr/bin/env python3
"""Build deterministic duplicate clusters for mycelial observations."""
from __future__ import annotations

from mycelial_observation_common import DEDUPES, NORMALIZED, dedupe_rows, load_jsonl, parser, write_jsonl


def main() -> int:
    args = parser(__doc__ or "dedupe mycelial observations").parse_args()
    rows, clusters = dedupe_rows(load_jsonl(args.input or NORMALIZED))
    write_jsonl(args.output or NORMALIZED, rows)
    write_jsonl(DEDUPES, clusters)
    print(f"wrote {len(clusters)} mycelial duplicate clusters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
