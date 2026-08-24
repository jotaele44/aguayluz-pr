#!/usr/bin/env python3
"""Ingest USGS monitoring-location metadata into the regulatory observation store.

First live provider for the PR #120 regulatory ingestion framework
(``docs/ROAD_TO_100.md``'s ``AYL-008``). USGS is first because
``scripts/ingest_usgs_field_measurements.py`` and siblings already prove the OGC API
(``api.waterdata.usgs.gov``) is keyless and reachable, and
``research/regulatory/contracts.py``'s ``PROVIDER_BASELINE_CAPABILITIES`` already
scopes USGS to entity records only (site metadata — never a permit or enforcement
authority).

This script *is* the scheduler for this provider: a plain CLI meant to be invoked by
cron/CI/systemd-timer on a recurring cadence, never an embedded APScheduler —
``research/regulatory/contracts.py``'s design-only status explicitly forbids that
dependency. Each run: load the saved checkpoint -> discover page locators -> fetch
each page -> normalize into observations -> persist -> save the checkpoint.

Idempotent on rerun: an observation's id is a stable hash of provider + site + a hash
of that site's own properties + normalization version (see
``aguayluz.regulatory_adapters.usgs.normalize``'s docstring for why it is not keyed
off the page's own bytes), so re-fetching an unchanged site reproduces the same
observation id and ``regulatory_db``'s merge-by-id replaces rather than duplicates
the row. Live-verified: two independent live runs over the same page range produced
the same 1000 observation ids while contributing 20 new receipts each (receipts are
retrieval-event provenance, so they correctly accumulate rather than collapse).

``--recheck-stale`` (fifth increment, ``AYL-008``'s freshness refresh) skips full bbox
discovery entirely. It first flags any ``current`` observation older than
``--stale-after-days`` as ``stale`` (``aguayluz.regulatory_adapters.usgs.mark_stale``),
then reconfirms every currently-stale site by its own site number
(``fetch_site`` — a single-ID lookup, not a full re-crawl). An unchanged site's
re-normalized content reproduces the exact same ``observation_id`` with
``freshness_state`` reset to ``current`` — a real reconfirmation. A **changed** site
mints a new, separate ``observation_id``; the old ``stale`` row is not deleted or
linked via ``supersedes_observation_id`` yet (an honest, recorded scope limit, not a
silent gap — a future increment can wire that once there is a real changed-site case
to design against).

    python scripts/ingest_regulatory_usgs.py                  # live, keyless
    python scripts/ingest_regulatory_usgs.py --reset-checkpoint
    python scripts/ingest_regulatory_usgs.py --recheck-stale
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

# Reuse the repo's own PR bounding box rather than hand-typing a second copy.
from aguayluz.regulatory_adapters.usgs import (  # noqa: E402
    DEFAULT_LIMIT,
    DEFAULT_STALE_AFTER_DAYS,
    discover,
    fetch,
    fetch_site,
    mark_stale,
    normalize,
)
from aguayluz.regulatory_db import (  # noqa: E402
    load_checkpoint,
    load_regulatory_observations,
    save_checkpoint,
    write_regulatory_observations,
    write_regulatory_receipts,
)
from ingest_usgs_water import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN  # noqa: E402

PROVIDER = "USGS"
DEFAULT_BBOX = f"{LON_MIN},{LAT_MIN},{LON_MAX},{LAT_MAX}"


def _recheck_stale(stale_after_days: int) -> int:
    now = datetime.now(timezone.utc)
    newly_stale = mark_stale(load_regulatory_observations(), as_of=now, stale_after_days=stale_after_days)
    if newly_stale:
        write_regulatory_observations(newly_stale)

    stale_sites = sorted({
        o["provider_record_id"] for o in load_regulatory_observations()
        if o["freshness_state"] == "stale"
    })
    if not stale_sites:
        print(f"marked {len(newly_stale)} observation(s) stale; no stale observations to recheck")
        return 0

    receipts: list[dict] = []
    reconfirmed: list[dict] = []
    failed = 0
    for site_no in stale_sites:
        try:
            raw, receipt = fetch_site(site_no)
        except Exception as e:  # noqa: BLE001
            print(f"recheck fetch failed for site {site_no} ({e})", file=sys.stderr)
            failed += 1
            continue
        receipts.append(receipt)
        reconfirmed.extend(normalize(raw, receipt))

    if receipts:
        write_regulatory_receipts(receipts)
    if reconfirmed:
        write_regulatory_observations(reconfirmed)

    print(
        f"marked {len(newly_stale)} observation(s) stale (older than {stale_after_days}d)\n"
        f"rechecked {len(stale_sites)} stale site(s), {failed} failed\n"
        f"reconfirmed {len(reconfirmed)} observation(s) -> data/regulatory_observations.jsonl"
    )
    return 1 if failed and not receipts else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--bbox", default=DEFAULT_BBOX, help="minlon,minlat,maxlon,maxlat.")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Page size.")
    ap.add_argument(
        "--reset-checkpoint", action="store_true",
        help="Ignore any saved checkpoint and start discovery from page 0.",
    )
    ap.add_argument(
        "--recheck-stale", action="store_true",
        help="Skip discovery; mark aged observations stale and reconfirm just those sites.",
    )
    ap.add_argument(
        "--stale-after-days", type=int, default=DEFAULT_STALE_AFTER_DAYS,
        help="Age (days) after which a current observation is flagged stale.",
    )
    args = ap.parse_args()

    if args.recheck_stale:
        return _recheck_stale(args.stale_after_days)

    checkpoint = None if args.reset_checkpoint else load_checkpoint(PROVIDER)
    locators, next_checkpoint = discover(bbox=args.bbox, checkpoint=checkpoint, limit=args.limit)

    receipts: list[dict] = []
    observations: list[dict] = []
    failed = 0
    for locator in locators:
        try:
            raw, receipt = fetch(locator)
        except Exception as e:  # noqa: BLE001
            print(f"fetch failed for {locator['locator']} ({e})", file=sys.stderr)
            failed += 1
            continue
        receipts.append(receipt)
        page_observations = normalize(raw, receipt)
        observations.extend(page_observations)
        # A short page (fewer results than the requested limit) means we reached the
        # end of the collection for this bbox; stop fetching the remaining locators
        # in this batch rather than spending calls on pages we already know are past
        # the end.
        if len(page_observations) < args.limit:
            break

    if receipts:
        write_regulatory_receipts(receipts)
    if observations:
        write_regulatory_observations(observations)
    save_checkpoint(PROVIDER, next_checkpoint)

    print(
        f"source: live USGS OGC monitoring-locations ({len(locators)} page locator(s) planned)\n"
        f"fetched {len(receipts)} page(s), failed {failed}\n"
        f"wrote {len(observations)} observation(s) -> data/regulatory_observations.jsonl\n"
        f"wrote {len(receipts)} receipt(s) -> data/regulatory_source_receipts.jsonl\n"
        f"checkpoint saved -> data/regulatory_checkpoints/{PROVIDER}.json (cursor={next_checkpoint['cursor']})"
    )
    return 1 if failed and not receipts else 0


if __name__ == "__main__":
    raise SystemExit(main())
