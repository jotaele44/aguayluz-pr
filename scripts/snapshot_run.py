#!/usr/bin/env python3
"""Snapshot the current outputs/ entity files under outputs/history/<run_id>/."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import OUTPUTS_DIR  # noqa: E402
from aguayluz.history import snapshot_run  # noqa: E402


def _make_run_id(slug: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{slug}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Snapshot current outputs/ for diff tracking")
    p.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR)
    p.add_argument("--run-id", default=None,
                   help="Stable run identifier; defaults to YYYYMMDDTHHMMSSZ_snapshot")
    p.add_argument("--slug", default="snapshot",
                   help="Slug appended to the auto-generated run_id when --run-id is omitted")
    args = p.parse_args(argv)

    run_id = args.run_id or _make_run_id(args.slug)
    run_dir = snapshot_run(args.outputs_dir, run_id)
    print(f"snapshot={run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
