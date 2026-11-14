"""Safely remove only the review-queue fixture created by this run.

Never delete on malformed/stale ownership evidence or when the fixture was
replaced, even if an old marker remains. A non-zero exit is a release gate.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_workspace = os.getenv("AGUAYLUZ_DATA_HOME", "").strip()
OUTPUTS = Path(_workspace) / "exports" if _workspace else REPO_ROOT / "outputs"
REVIEW_QUEUE = OUTPUTS / "review_queue.json"
SEED_MARKER = OUTPUTS / ".review_queue.seeded"


def main() -> int:
    if not _workspace:
        print("gui_parity_teardown: AGUAYLUZ_DATA_HOME is required", file=sys.stderr)
        return 2
    if not SEED_MARKER.exists():
        # No authority to remove any file without an ownership marker.
        return 0
    try:
        record = json.loads(SEED_MARKER.read_text(encoding="utf-8"))
        if record.get("schema_version") != 1:
            raise ValueError("unsupported ownership schema")
        expected_run = os.getenv("AGUAYLUZ_GUI_PARITY_RUN_ID", "").strip()
        if expected_run and record.get("run_id") != expected_run:
            raise ValueError("fixture belongs to another run")
        if record.get("target") != str(REVIEW_QUEUE.resolve()):
            raise ValueError("fixture target path changed")
        if REVIEW_QUEUE.is_symlink() or SEED_MARKER.is_symlink():
            raise ValueError("symlink ownership is forbidden")
        stat = REVIEW_QUEUE.stat()
        if stat.st_dev != record.get("st_dev") or stat.st_ino != record.get("st_ino"):
            raise ValueError("fixture identity changed since seed")
        contents = REVIEW_QUEUE.read_bytes()
        if len(contents) != record.get("size"):
            raise ValueError("fixture size changed")
        if hashlib.sha256(contents).hexdigest() != record.get("sha256"):
            raise ValueError("fixture content changed")
        REVIEW_QUEUE.unlink()
        SEED_MARKER.unlink()
        print(f"gui_parity_teardown: removed owned fixture {REVIEW_QUEUE}")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"gui_parity_teardown: REFUSED cleanup; evidence preserved: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
