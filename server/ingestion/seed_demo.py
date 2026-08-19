"""Seed a minimal review queue so the GUI parity run has something to render.

`dashboard/gui-parity.playwright.config.mjs` already looks for this file and, when
it exists, runs it before uvicorn::

    python server/ingestion/seed_demo.py && python -m uvicorn server.backend.app:app ...

That branch had never fired, because the file did not exist. The consequence is
easy to miss and worth stating plainly: ``outputs/`` is gitignored apart from
``.gitkeep``, and the GUI Reachability E2E job runs no exporter, so in CI
``outputs/review_queue.json`` is absent, ``GET /review-queue`` returns
``{"total": 0, "items": []}``, and ``/review`` renders "no items". The
reachability spec was asserting that a route with no data in it does not crash —
a gate passing over something it never examined.

Two rules keep the fixture from becoming a liability:

*Never replace real data.* A working checkout's export is thousands of records.
If ``review_queue.json`` already exists it is left completely alone.

*Never leave fake data behind.* When this script does write the fixture it also
drops a marker file beside it. ``gui_parity_teardown.py`` removes the queue file
only when that marker is present, so a seeded run cleans up after itself and a
later ordinary backend run cannot serve ``SEED-*`` records as if they were real.
Without the marker a teardown could not tell a fixture apart from an export.

The backend re-reads this file on every request (``_load_json`` is called inside
the ``/review-queue`` handler, unlike the JSONL corpora loaded at import), so a
seed written here is picked up without a restart.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Mirrors server/backend/main.py: AGUAYLUZ_DATA_HOME repoints both DATA and
# OUTPUTS, and OUTPUTS is named "exports" under a custom workspace.
_workspace = os.getenv("AGUAYLUZ_DATA_HOME", "").strip()
OUTPUTS = Path(_workspace) / "exports" if _workspace else REPO_ROOT / "outputs"

REVIEW_QUEUE = OUTPUTS / "review_queue.json"
# Presence of this marker is the only thing that authorises deleting the queue
# file. It means "this run created that file", never "this file is disposable".
SEED_MARKER = OUTPUTS / ".review_queue.seeded"

# Deliberately small and deliberately mixed. `block` comes first because
# ReviewPage does no client-side sort — it renders backend file order, sliced to
# PAGE_SIZE = 25 — so a record appended to the end of a real export would sit on
# a page nobody looks at. The severities mirror scripts/federation_export.py,
# which writes "warn" when review_status == "needs_review" and "block" otherwise.
_ITEMS = [
    {
        "record_ref": "SEED-BLOCK-0001",
        "reason": "seeded fixture: blocked record for GUI parity",
        "severity": "block",
        "evidence_tier": "T1",
        "confidence": 91,
    },
    {
        "record_ref": "SEED-WARN-0001",
        "reason": "seeded fixture: needs-review record for GUI parity",
        "severity": "warn",
        "evidence_tier": "T2",
        "confidence": 64,
    },
    {
        "record_ref": "SEED-WARN-0002",
        "reason": "seeded fixture: second needs-review record",
        "severity": "warn",
        "evidence_tier": "T3",
        "confidence": 38,
    },
]


def main() -> int:
    if REVIEW_QUEUE.exists():
        print(f"seed_demo: {REVIEW_QUEUE} already present — leaving it alone")
        return 0

    payload = {"total": len(_ITEMS), "offset": 0, "items": _ITEMS}
    try:
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        REVIEW_QUEUE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        # Written after the queue file, so a crash between the two leaves no
        # marker and the teardown declines to delete anything.
        SEED_MARKER.write_text(
            "Written by server/ingestion/seed_demo.py. Presence of this file means\n"
            "review_queue.json is a GUI-parity fixture and may be removed by\n"
            "server/ingestion/gui_parity_teardown.py.\n",
            encoding="utf-8",
        )
    except OSError as exc:
        # The playwright config chains this with `&&`, so a non-zero exit fails
        # the whole webServer boot rather than starting a backend with no data.
        print(f"seed_demo: could not write {REVIEW_QUEUE}: {exc}", file=sys.stderr)
        return 1

    print(f"seed_demo: wrote {len(_ITEMS)} review-queue records to {REVIEW_QUEUE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
