#!/usr/bin/env python3
"""Persist MiLUMA regional outage-status snapshots without inventing regional semantics.

The source manifestation is retained as a whole JSON payload inside an append-only JSONL
history. No field is renamed into a canonical metric until the upstream schema is frozen
from observed bytes.

Each row records:
- retrieval timestamp
- exact source endpoint
- SHA-256 of canonical JSON serialization of the raw payload
- raw payload type
- raw payload itself

Repeated ingestion of the same timestamp+payload is idempotent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_SRC = "/tmp/luma_regions_without_service.json"
DEFAULT_OUT = "data/luma_status_snapshots.jsonl"
DEFAULT_SOURCE_REF = (
    "https://api.miluma.lumapr.com/miluma-outage-api/outage/regionsWithoutService"
)


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def snapshot_row(payload: Any, snapshot_ts: str, source_ref: str) -> dict[str, Any]:
    digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return {
        "snapshot_id": f"LUMA_REGIONS_{snapshot_ts}_{digest[:12]}",
        "snapshot_ts": snapshot_ts,
        "source_ref": source_ref,
        "payload_sha256": digest,
        "payload_type": type(payload).__name__,
        "raw_payload": payload,
        "evidence_tier": "T2",
        "review_status": "needs_review",
        "schema_state": "RAW_UNFROZEN",
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_no}: expected object row")
        rows.append(row)
    return rows


def append_idempotent(path: Path, row: dict[str, Any]) -> tuple[int, bool]:
    rows = load_rows(path)
    key = (row["snapshot_ts"], row["payload_sha256"])
    if any((r.get("snapshot_ts"), r.get("payload_sha256")) == key for r in rows):
        return len(rows), False
    rows.append(row)
    rows.sort(key=lambda r: (str(r.get("snapshot_ts", "")), str(r.get("payload_sha256", ""))))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )
    return len(rows), True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--snapshot-ts", required=True)
    ap.add_argument("--source-ref", default=DEFAULT_SOURCE_REF)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    src = Path(args.src)
    payload = json.loads(src.read_text(encoding="utf-8"))
    row = snapshot_row(payload, args.snapshot_ts, args.source_ref)
    count, added = append_idempotent(Path(args.out), row)
    state = "appended" if added else "already-present"
    print(
        f"{state}: {row['snapshot_id']} payload_sha256={row['payload_sha256']} "
        f"history_rows={count} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
