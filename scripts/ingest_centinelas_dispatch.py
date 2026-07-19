#!/usr/bin/env python3
"""Ingest a Centinelas repository_dispatch payload into service_events.jsonl.

The federation egress hop: centinelas-pr classifies a PR water/utility signal as
ENVIRONMENTAL, routes it to aguayluz-pr, and POSTs a GitHub ``repository_dispatch``
(``centinelas-signal``) whose ``client_payload`` is the routed intake record
(title, source_url, published_at, and the water sub-taxonomy ``domain_tags``). This
adapter maps that payload onto a ``service_event`` via the existing
``ingest_news_event.build_event`` (evidence tier T3, review_status=needs_review),
so a Centinelas water signal lands in the same corpus as the manual news path.

Input (first available): ``--payload <file>``, ``--payload-json <str>``, or the
``CENTINELAS_CLIENT_PAYLOAD`` env var (JSON). Idempotent merge by event_id.
Stdlib + the local ingest_news_event module only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from argparse import Namespace
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_news_event import (  # noqa: E402
    OUT_DEFAULT,
    VALID_EVENT_TYPES,
    _read_jsonl,
    _write_jsonl,
    build_event,
)

# Water/utility sub-taxonomy tag -> aguayluz ServiceEvent event_type. Highest-
# priority tag present wins; anything untagged is a generic project_update signal.
_TAG_TO_EVENT_TYPE: list[tuple[str, str]] = [
    ("boil_water", "boil_water"),
    ("water_quality", "water_quality_violation"),
    ("wastewater", "contamination_incident"),
    ("power_grid", "outage"),
    ("reservoir_drought", "service_interruption"),
    ("flood", "service_interruption"),
    ("potable_water", "service_interruption"),
]
_DEFAULT_EVENT_TYPE = "project_update"


def event_type_for(domain_tags: list[str]) -> str:
    tags = set(domain_tags or [])
    for tag, etype in _TAG_TO_EVENT_TYPE:
        if tag in tags:
            return etype
    return _DEFAULT_EVENT_TYPE


def _payload_date(payload: dict) -> date:
    raw = payload.get("published_at") or payload.get("captured_at")
    if raw:
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return datetime.now().date()  # noqa: DTZ005 — date only, provenance is the payload


def payload_to_event(payload: dict) -> dict:
    """Map a Centinelas intake record into an aguayluz service_event row."""
    event_type = event_type_for(payload.get("domain_tags") or [])
    if event_type not in VALID_EVENT_TYPES:  # defensive; mapping is closed
        event_type = _DEFAULT_EVENT_TYPE
    args = Namespace(
        url=payload.get("source_url") or payload.get("item_id") or "unknown",
        title=payload.get("title") or "Centinelas signal",
        municipality=payload.get("municipality"),
        affected_area=None,
        zone=None,
        event_type=event_type,
        date=_payload_date(payload),
        slug=None,
        tier="T3",
        confidence=int(round(float(payload.get("confidence") or 0.6) * 100))
        if payload.get("confidence") is not None else 60,
        link_asset=[],
    )
    return build_event(args)


def _load_payload(args: argparse.Namespace) -> dict:
    if args.payload:
        raw = Path(args.payload).read_text()
    elif args.payload_json:
        raw = args.payload_json
    else:
        raw = os.environ.get("CENTINELAS_CLIENT_PAYLOAD", "")
    if not raw.strip():
        sys.exit("no payload: pass --payload/--payload-json or set CENTINELAS_CLIENT_PAYLOAD")
    return json.loads(raw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--payload", default=None, help="path to a JSON client_payload file")
    ap.add_argument("--payload-json", default=None, help="inline JSON client_payload")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    row = payload_to_event(_load_payload(args))
    if args.dry_run:
        print(json.dumps(row, indent=2, ensure_ascii=False))
        return 0

    out = Path(args.out)
    by_id = {e["event_id"]: e for e in _read_jsonl(out)}
    is_new = row["event_id"] not in by_id
    by_id[row["event_id"]] = row
    _write_jsonl(out, list(by_id.values()))
    print(f"{'added' if is_new else 'updated'}: {row['event_id']} "
          f"({row['event_type']}) from Centinelas dispatch -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
