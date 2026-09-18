#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "aguayluz_test_execution_receipt_v1"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write a test-execution receipt after a successfully completed pytest command."
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--command", required=True)
    parser.add_argument("--suite", default="FULL", choices=["FULL", "FOCUSED"])
    args = parser.parse_args(argv)

    if "pytest" not in args.command:
        raise SystemExit("--command must identify the pytest command that already completed successfully")

    commit_sha = _git("rev-parse", "HEAD")
    tree_sha = _git("rev-parse", "HEAD^{tree}")
    github_sha = os.environ.get("GITHUB_SHA")
    if github_sha and github_sha != commit_sha:
        raise SystemExit(f"GITHUB_SHA {github_sha} does not match checkout HEAD {commit_sha}")

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "repository": "jotaele44/aguayluz-pr",
        "commit_sha": commit_sha,
        "tree_sha": tree_sha,
        "status": "PASS",
        "suite": args.suite,
        "command": args.command,
        "completed_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "runner": "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
