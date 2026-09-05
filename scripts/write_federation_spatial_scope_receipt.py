#!/usr/bin/env python3
"""Bind the federation spatial certification scope to the producer Git identity."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCOPE_REL = "governance/federation_spatial_certification_scope_v1.json"
SCHEMA_VERSION = "prii_federation_spatial_certification_scope_receipt_v1"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_receipt() -> dict[str, Any]:
    path = ROOT / SCOPE_REL
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"scope file missing or invalid: {SCOPE_REL}")
    scope = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(scope, dict):
        raise ValueError("scope root must be an object")
    if scope.get("schema_version") != "prii_federation_spatial_certification_scope_v1":
        raise ValueError("scope schema_version mismatch")
    if scope.get("claim") != "FEDERATION_SPATIAL_ARCHITECTURE":
        raise ValueError("scope claim mismatch")
    if scope.get("consumer_authority") != "jotaele44/thehub-pr":
        raise ValueError("scope consumer authority mismatch")

    commit = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    blob = _git("rev-parse", f"HEAD:{SCOPE_REL}")
    if len(commit) != 40 or len(tree) != 40 or len(blob) != 40:
        raise ValueError("invalid Git identity length")

    return {
        "schema_version": SCHEMA_VERSION,
        "state": "PASS",
        "claim": scope["claim"],
        "claim_version": scope.get("claim_version"),
        "producer_repository": "jotaele44/aguayluz-pr",
        "producer_commit": commit,
        "producer_tree": tree,
        "scope_path": SCOPE_REL,
        "scope_bytes": path.stat().st_size,
        "scope_sha256": _sha256(path),
        "scope_git_blob_sha": blob,
        "scope_status": scope.get("status"),
        "problems": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/federation_spatial_certification_scope_receipt.json"),
    )
    args = parser.parse_args(argv)
    try:
        receipt = build_receipt()
    except Exception as exc:  # noqa: BLE001 - fail closed
        payload = {
            "schema_version": SCHEMA_VERSION,
            "state": "BLOCKED",
            "problems": [f"{type(exc).__name__}: {exc}"],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
