#!/usr/bin/env python3
"""Generate regulatory entity-link candidates from stored observations.

Pure candidate generation lives in ``src/aguayluz/regulatory_links.py`` (hard
identifier matching against ``data/utility_assets.jsonl``, currently USGS site
numbers only). This script does the I/O: load observations + assets, generate
candidates, write only the ones that are genuinely new.

**Never overwrites an existing candidate.** ``candidate_id`` is a deterministic hash
of ``(observation_id, candidate_asset_id)`` only — never of ``decision_state`` or
``contradictions`` — so regenerating candidates for an unchanged observation
reproduces the exact same ids every time. This script diffs against what is already
on record and writes only the ids that are not there yet, so a human's prior decision
(``approved``, ``rejected``, ``needs_review``) is never silently reset back to
``proposed`` by a rerun. Approval itself never happens here — only through
``POST /regulatory/links/{candidate_id}/decide`` (``server/backend/regulatory_api.py``).

    python scripts/build_regulatory_links.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz import DATA_DIR  # noqa: E402
from aguayluz.regulatory_db import (  # noqa: E402
    load_regulatory_links,
    load_regulatory_observations,
    write_regulatory_links,
)
from aguayluz.regulatory_links import generate_all_candidates  # noqa: E402

UTILITY_ASSETS_PATH = DATA_DIR / "utility_assets.jsonl"


def _load_assets(path: Path = UTILITY_ASSETS_PATH) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    observations = load_regulatory_observations()
    assets = _load_assets()
    generated = generate_all_candidates(observations, assets)
    if not generated:
        print(f"generated 0 candidates from {len(observations)} observation(s); nothing to do")
        return 0

    existing_ids = {c["candidate_id"] for c in load_regulatory_links()}
    new_candidates = [c for c in generated if c["candidate_id"] not in existing_ids]
    if not new_candidates:
        print(
            f"generated {len(generated)} candidate(s) from {len(observations)} observation(s); "
            f"all already on record, nothing new to write"
        )
        return 0

    write_regulatory_links(new_candidates)
    proposed = sum(1 for c in new_candidates if c["decision_state"] == "proposed")
    needs_review = sum(1 for c in new_candidates if c["decision_state"] == "needs_review")
    print(
        f"generated {len(generated)} candidate(s) from {len(observations)} observation(s)\n"
        f"wrote {len(new_candidates)} new candidate(s) (proposed={proposed}, needs_review={needs_review})\n"
        f"-> data/regulatory_entity_links.jsonl"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
