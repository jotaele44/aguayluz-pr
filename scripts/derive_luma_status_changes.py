#!/usr/bin/env python3
"""Derive conservative change observations from preserved MiLUMA status snapshots.

This module deliberately stops short of outage/restoration inference. Public LUMA ERP
documentation establishes that OMS/web interfaces can be disabled during major events
and that restoration information can be manually captured. Therefore a payload change
or disappearance is evidence of SOURCE_STATE_CHANGE only, never by itself restoration.

Input rows remain the append-only RAW_UNFROZEN snapshots created by
scripts/ingest_luma_status.py. Output rows compare adjacent snapshots without requiring
or inventing a regional payload schema.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_SRC = "data/luma_status_snapshots.jsonl"
DEFAULT_OUT = "data/luma_status_changes.jsonl"


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_no}: expected object row")
        rows.append(row)
    return rows


def classify_pair(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev_hash = str(previous.get("payload_sha256", ""))
    curr_hash = str(current.get("payload_sha256", ""))
    changed = prev_hash != curr_hash
    return {
        "change_id": (
            f"LUMA_STATUS_CHANGE_{previous.get('snapshot_ts', '')}_"
            f"{current.get('snapshot_ts', '')}_{prev_hash[:8]}_{curr_hash[:8]}"
        ),
        "previous_snapshot_id": previous.get("snapshot_id"),
        "current_snapshot_id": current.get("snapshot_id"),
        "previous_snapshot_ts": previous.get("snapshot_ts"),
        "current_snapshot_ts": current.get("snapshot_ts"),
        "previous_payload_sha256": prev_hash,
        "current_payload_sha256": curr_hash,
        "observation": "SOURCE_STATE_CHANGE" if changed else "SOURCE_STATE_UNCHANGED",
        "restoration_state": "UNRESOLVED",
        "outage_lifecycle_state": "UNRESOLVED",
        "schema_state": "RAW_UNFROZEN",
        "reason": (
            "payload hashes differ; source documentation does not permit restoration "
            "inference from snapshot disappearance/change alone"
            if changed
            else "payload hashes are identical"
        ),
    }


def derive_changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda r: (
            str(r.get("snapshot_ts", "")),
            str(r.get("payload_sha256", "")),
        ),
    )
    return [
        classify_pair(previous, current)
        for previous, current in zip(ordered, ordered[1:], strict=False)
    ]


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    snapshots = load_rows(Path(args.src))
    changes = derive_changes(snapshots)
    write_rows(Path(args.out), changes)
    print(f"snapshots={len(snapshots)} adjacent_changes={len(changes)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
