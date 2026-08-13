"""Remove the review-queue fixture that seed_demo.py created, and nothing else.

Run as Playwright's globalTeardown. The guard is the marker file: this deletes
``review_queue.json`` only when ``.review_queue.seeded`` sits beside it, which
only ``seed_demo.py`` writes and only after it has created the queue file
itself. A real export never has the marker, so it can never be deleted here.

Without this, a developer who ran ``npm run test:gui-parity`` on a checkout with
no export would be left holding three ``SEED-*`` records in
``outputs/review_queue.json``. Nothing marks them as fake, the backend would
serve them as review data, and seed_demo's own "already present" check would
then skip forever — a fixture quietly promoted to real data.
"""

from __future__ import annotations

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
        REVIEW_QUEUE.unlink(missing_ok=True)
        SEED_MARKER.unlink(missing_ok=True)
    except OSError as exc:
        # Teardown failure must not fail the run — the tests already passed or
        # failed on their own merits. Report and move on.
        print(f"gui_parity_teardown: could not remove the fixture: {exc}", file=sys.stderr)
        return 0

    print(f"gui_parity_teardown: removed the seeded fixture at {REVIEW_QUEUE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
