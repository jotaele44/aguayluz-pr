#!/usr/bin/env python3
"""Classify two ZIP manifestations by member payload identity.

Outer SHA-256 differences establish byte difference only. This comparator
freezes each member as PATH + UNCOMPRESSED_SIZE + SHA256 and separately
compares the payload multiset SIZE + SHA256.

Terminal classes:
- BYTE_IDENTICAL
- PURE_RECOMPRESSION
- SAME_PAYLOADS_DIFFERENT_PATHS
- DISTINCT_PAYLOADS
- UNRESOLVED
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def member_manifest(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise ValueError(f"ZIP integrity failure at member {bad}")
        for info in zf.infolist():
            if info.is_dir():
                continue
            payload = zf.read(info.filename)
            rows.append(
                {
                    "path": info.filename,
                    "uncompressed_size": info.file_size,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    rows.sort(key=lambda x: x["path"])
    return rows


def classify(old_zip: Path, new_zip: Path) -> dict[str, Any]:
    old_outer = sha256_file(old_zip)
    new_outer = sha256_file(new_zip)
    old_members = member_manifest(old_zip)
    new_members = member_manifest(new_zip)

    old_by_path = {(x["path"], x["uncompressed_size"], x["sha256"]) for x in old_members}
    new_by_path = {(x["path"], x["uncompressed_size"], x["sha256"]) for x in new_members}
    old_payloads = Counter((x["uncompressed_size"], x["sha256"]) for x in old_members)
    new_payloads = Counter((x["uncompressed_size"], x["sha256"]) for x in new_members)

    if old_outer == new_outer:
        state = "BYTE_IDENTICAL"
    elif old_by_path == new_by_path:
        state = "PURE_RECOMPRESSION"
    elif old_payloads == new_payloads:
        state = "SAME_PAYLOADS_DIFFERENT_PATHS"
    else:
        state = "DISTINCT_PAYLOADS"

    old_paths = {x["path"]: x for x in old_members}
    new_paths = {x["path"]: x for x in new_members}
    all_paths = sorted(set(old_paths) | set(new_paths))
    path_deltas = []
    for p in all_paths:
        a, b = old_paths.get(p), new_paths.get(p)
        if a != b:
            path_deltas.append({"path": p, "old": a, "new": b})

    return {
        "schema_version": "aguayluz.archive_manifestation_adjudication/v1",
        "classification": state,
        "old": {
            "path": str(old_zip),
            "outer_sha256": old_outer,
            "member_count": len(old_members),
            "members": old_members,
        },
        "new": {
            "path": str(new_zip),
            "outer_sha256": new_outer,
            "member_count": len(new_members),
            "members": new_members,
        },
        "member_path_identity": old_by_path == new_by_path,
        "payload_multiset_identity": old_payloads == new_payloads,
        "path_deltas": path_deltas,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("old_zip", type=Path)
    p.add_argument("new_zip", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--allow",
        action="append",
        default=[],
        help="Allowed terminal classification; repeatable. If supplied, other states fail.",
    )
    args = p.parse_args()
    try:
        receipt = classify(args.old_zip, args.new_zip)
    except Exception as exc:  # noqa: BLE001
        receipt = {
            "schema_version": "aguayluz.archive_manifestation_adjudication/v1",
            "classification": "UNRESOLVED",
            "error": str(exc),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    if args.allow and receipt["classification"] not in set(args.allow):
        return 2
    return 0 if receipt["classification"] != "UNRESOLVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
