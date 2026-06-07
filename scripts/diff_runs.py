#!/usr/bin/env python3
"""Diff two snapshotted runs; writes outputs/run_diff.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import OUTPUTS_DIR  # noqa: E402
from aguayluz.history import diff_runs, list_snapshots  # noqa: E402
from aguayluz.models import validate_against_schema  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Diff two snapshotted runs")
    p.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR)
    p.add_argument("--from", dest="run_from", default=None,
                   help="Source run_id; defaults to the second-most-recent snapshot")
    p.add_argument("--to", dest="run_to", default=None,
                   help="Target run_id; defaults to the most recent snapshot")
    args = p.parse_args(argv)

    history_root = args.outputs_dir / "history"
    snapshots = list_snapshots(history_root)
    if len(snapshots) < 2 and not (args.run_from and args.run_to):
        print(
            f"diff_runs: need at least 2 snapshots in {history_root} "
            "(or pass --from and --to explicitly)",
            file=sys.stderr,
        )
        return 1

    run_from = args.run_from or snapshots[-2]
    run_to = args.run_to or snapshots[-1]
    diff = diff_runs(history_root=history_root, run_from=run_from, run_to=run_to)
    validate_against_schema("run_diff", diff)
    (args.outputs_dir / "run_diff.json").write_text(
        json.dumps(diff, indent=2), encoding="utf-8"
    )
    print(f"diff: {diff['summary']['headline']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
