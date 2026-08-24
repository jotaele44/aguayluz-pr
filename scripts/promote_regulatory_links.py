#!/usr/bin/env python3
"""Project approved regulatory entity links into a durable crosswalk.

Fifth and final implementation increment for the PR #120 regulatory ingestion
framework (docs/ROAD_TO_100.md's AYL-008). Pure promotion logic lives in
``src/aguayluz/regulatory_promotion.py``; this script does the I/O.

**Never sets ``decision_state="approved"`` itself.** It only reads
``data/regulatory_entity_links.jsonl`` rows a human already approved through
``POST /regulatory/links/{candidate_id}/decide`` (``server/backend/regulatory_api.py``,
fail-closed on open contradictions), and writes each into
``data/regulatory_entity_crosswalk.jsonl``. Idempotent: ``crosswalk_id`` derives
deterministically from ``candidate_id``, and ``write_regulatory_crosswalk`` merges by
that id, so rerunning after no new approvals changes nothing.

    python scripts/promote_regulatory_links.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz.regulatory_db import (  # noqa: E402
    load_regulatory_links,
    load_regulatory_observations,
    write_regulatory_crosswalk,
)
from aguayluz.regulatory_promotion import promote_approved_links  # noqa: E402


def main() -> int:
    links = load_regulatory_links()
    observations = load_regulatory_observations()
    rows = promote_approved_links(links, observations)

    approved_count = sum(1 for c in links if c.get("decision_state") == "approved")
    skipped = approved_count - len(rows)

    if not rows:
        print(
            f"{approved_count} approved link(s) on record, 0 promotable "
            f"(skipped {skipped} with no matching observation); nothing to do"
        )
        return 0

    write_regulatory_crosswalk(rows)
    print(
        f"{approved_count} approved link(s) on record\n"
        f"wrote {len(rows)} crosswalk row(s)"
        + (f" (skipped {skipped} with no matching observation)" if skipped else "")
        + "\n-> data/regulatory_entity_crosswalk.jsonl"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
