#!/usr/bin/env python3
"""Verify normalized mycelial observations and write status records."""
from __future__ import annotations

from mycelial_observation_common import DEDUPES, NORMALIZED, VERIFIED, VERIFICATIONS, load_jsonl, parser, verify_rows, write_jsonl


def main() -> int:
    args = parser(__doc__ or "verify mycelial observations").parse_args()
    rows, statuses = verify_rows(load_jsonl(args.input or NORMALIZED), load_jsonl(DEDUPES))
    write_jsonl(args.output or VERIFIED, rows)
    write_jsonl(VERIFICATIONS, statuses)
    print(f"wrote {len(rows)} verified mycelial observations and {len(statuses)} statuses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
