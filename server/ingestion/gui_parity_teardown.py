"""Remove the review-queue fixture that seed_demo.py created, and nothing else.

Run as Playwright's globalTeardown. Cleanup requires both the seed marker and
its SHA-256 binding to the current queue bytes. If a real export has replaced
the fixture, or a legacy marker has no hash, both files are preserved for review.

Without this, a developer who ran ``npm run test:gui-parity`` on a checkout with
no export would be left holding three ``SEED-*`` records in
``outputs/review_queue.json``. Nothing marks them as fake, the backend would
serve them as review data, and seed_demo's own "already present" check would
then skip forever — a fixture quietly promoted to real data.
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
    if not SEED_MARKER.exists():
        # Either nothing was seeded, or what is there is a real export. Both
        # mean: do not touch it.
        return 0

    try:
        marker = json.loads(SEED_MARKER.read_text(encoding="utf-8"))
        expected = marker.get("sha256") if isinstance(marker, dict) else None
        if REVIEW_QUEUE.exists():
            actual = hashlib.sha256(REVIEW_QUEUE.read_bytes()).hexdigest()
            if actual != expected:
                print("gui_parity_teardown: queue changed or marker is unverified; preserving it", file=sys.stderr)
                return 1
        REVIEW_QUEUE.unlink(missing_ok=True)
        SEED_MARKER.unlink(missing_ok=True)
    except (OSError, ValueError) as exc:
        # Signal failed cleanup to the caller; preserve anything unverified.
        print(f"gui_parity_teardown: could not remove the fixture: {exc}", file=sys.stderr)
        return 1

    print(f"gui_parity_teardown: removed the seeded fixture at {REVIEW_QUEUE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
