#!/usr/bin/env python3
"""Persist MiLUMA regional outage-status snapshots with receipt-bound provenance.

The raw source manifestation is retained as a whole JSON payload. No regional field is
promoted into a canonical metric until successful source bytes establish a stable schema.

When --snapshot-meta is supplied, ingestion requires a PASS receipt for the regional
endpoint and verifies the exact source-byte SHA-256 before appending. A recorded source
failure is a clean skip, not a zero-outage observation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_SRC = "/tmp/luma_regions_without_service.json"
DEFAULT_META = "/tmp/luma_snapshot_manifest.json"
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


def snapshot_row(
    payload: Any,
    snapshot_ts: str,
    source_ref: str,
    source_byte_sha256: str | None = None,
    source_byte_count: int | None = None,
) -> dict[str, Any]:
    logical_digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return {
        "snapshot_id": f"LUMA_REGIONS_{snapshot_ts}_{logical_digest[:12]}",
        "snapshot_ts": snapshot_ts,
        "source_ref": source_ref,
        "payload_sha256": logical_digest,
        "source_byte_sha256": source_byte_sha256,
        "source_byte_count": source_byte_count,
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
    key = (
        row["snapshot_ts"],
        row["payload_sha256"],
        row.get("source_byte_sha256"),
    )
    if any(
        (
            r.get("snapshot_ts"),
            r.get("payload_sha256"),
            r.get("source_byte_sha256"),
        )
        == key
        for r in rows
    ):
        return len(rows), False
    rows.append(row)
    rows.sort(
        key=lambda r: (
            str(r.get("snapshot_ts", "")),
            str(r.get("payload_sha256", "")),
            str(r.get("source_byte_sha256", "")),
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )
    return len(rows), True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--snapshot-meta", default=None)
    ap.add_argument("--snapshot-ts", default=None)
    ap.add_argument("--source-ref", default=DEFAULT_SOURCE_REF)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    src = Path(args.src)
    snapshot_ts = args.snapshot_ts
    source_ref = args.source_ref
    source_byte_sha256: str | None = None
    source_byte_count: int | None = None

    if args.snapshot_meta:
        meta_path = Path(args.snapshot_meta)
        if not meta_path.is_file():
            print(f"regional-source-unavailable: snapshot manifest missing ({meta_path}); skipping")
            return 0
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        entry = meta.get("regions")
        if not isinstance(entry, dict):
            raise ValueError("snapshot manifest lacks regions entry")
        if entry.get("status") != "PASS":
            state = entry.get("status", "UNRESOLVED")
            print(f"regional-source-{str(state).lower()}: skipping")
            return 0
        if not src.is_file():
            raise ValueError("regions receipt is PASS but source bytes are missing")

        snapshot_ts = entry.get("retrieval_utc")
        source_ref = entry.get("url")
        source_byte_sha256 = entry.get("response_sha256")
        source_byte_count = entry.get("response_bytes")
        if not all(
            isinstance(v, str) and v
            for v in (snapshot_ts, source_ref, source_byte_sha256)
        ):
            raise ValueError("PASS regions receipt lacks retrieval_utc/url/response_sha256")
        raw = src.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash != source_byte_sha256:
            raise ValueError(
                f"regional source hash mismatch: manifest={source_byte_sha256} "
                f"actual={actual_hash}"
            )
        if source_byte_count != len(raw):
            raise ValueError(
                f"regional source byte-count mismatch: manifest={source_byte_count} "
                f"actual={len(raw)}"
            )
    else:
        if not snapshot_ts:
            raise ValueError("--snapshot-ts is required without --snapshot-meta")
        raw = src.read_bytes()
        source_byte_sha256 = hashlib.sha256(raw).hexdigest()
        source_byte_count = len(raw)

    payload = json.loads(raw)
    row = snapshot_row(
        payload,
        str(snapshot_ts),
        str(source_ref),
        source_byte_sha256,
        source_byte_count,
    )
    count, added = append_idempotent(Path(args.out), row)
    state = "appended" if added else "already-present"
    print(
        f"{state}: {row['snapshot_id']} logical_sha256={row['payload_sha256']} "
        f"source_byte_sha256={row['source_byte_sha256']} "
        f"history_rows={count} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
