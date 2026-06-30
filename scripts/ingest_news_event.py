#!/usr/bin/env python3
"""Record a news- or announcement-sourced service event into service_events.jsonl.

Use this when an environmental incident, contamination event, or infrastructure
story surfaces in media or government press releases before it appears in a
structured regulatory feed (SDWIS, PREPS, etc.). Events created here carry
evidence_tier T3 (verifiable public source, not yet in a regulatory feed) and
review_status needs_review.

Examples:

  # Oil/grease contamination at an AAA pumping station (Radio Isla story):
  python scripts/ingest_news_event.py \\
    --url "https://radioisla.tv/recursos-naturales-activa-unidad-..." \\
    --title "DRNA investiga procedencia de grasa y aceite en estación AAA en Canóvanas" \\
    --municipality "Canóvanas" \\
    --event-type contamination_incident \\
    --date 2026-06-28 \\
    --link-asset AYL_AST_CANOVANAS_PUMP_001  # optional

  # With no linked asset, omit --link-asset.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DEFAULT = REPO / "data" / "service_events.jsonl"

VALID_EVENT_TYPES = [
    "outage",
    "restoration",
    "boil_water",
    "service_interruption",
    "water_quality_violation",
    "contamination_incident",
    "project_update",
    "unknown",
]
# Evidence tiers usable for news/announcement sources
NEWS_TIERS = ("T3", "T4")
EID_RE = re.compile(r"^AYL_EVT_[0-9]{8}_[A-Za-z0-9_-]+$")
SLUG_RE = re.compile(r"[^A-Za-z0-9_-]")


def _slug(text: str, maxlen: int = 40) -> str:
    return SLUG_RE.sub("-", text.strip())[:maxlen].strip("-")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def build_event(args: argparse.Namespace) -> dict:
    event_date: date = args.date
    day = event_date.strftime("%Y%m%d")
    slug = _slug(args.slug or args.title)
    event_id = f"AYL_EVT_{day}_{slug}"
    if not EID_RE.match(event_id):
        sys.exit(f"Generated event_id does not match schema pattern: {event_id!r}")

    start_iso = datetime.combine(event_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()

    row: dict = {
        "event_id": event_id,
        "event_type": args.event_type,
        "affected_area": args.municipality or args.affected_area or "Puerto Rico",
        "municipality": args.municipality or None,
        "zone": args.zone or None,
        "status_text": args.title,
        "start_time": start_iso,
        "end_time": None,
        "reported_customers_or_users": None,
        "source_ref": args.url,
        "source_hash": None,
        "evidence_tier": args.tier,
        "confidence": args.confidence,
        "review_status": "needs_review",
        "linked_asset_ids": args.link_asset or [],
    }
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="Canonical URL of the news article or announcement.")
    ap.add_argument("--title", required=True, help="Short human-readable description / headline.")
    ap.add_argument("--municipality", default=None,
                    help="Canonical PR municipio name (accented), e.g. 'Canóvanas'.")
    ap.add_argument("--affected-area", default=None,
                    help="Free-text area label when municipality is unknown.")
    ap.add_argument("--zone", default=None, help="Sub-municipal sector/barrio, if known.")
    ap.add_argument("--event-type", default="contamination_incident",
                    choices=VALID_EVENT_TYPES,
                    help="ServiceEvent event_type (default: contamination_incident).")
    ap.add_argument("--date", required=True, type=date.fromisoformat,
                    help="Event date ISO-8601 (YYYY-MM-DD).")
    ap.add_argument("--slug", default=None,
                    help="Override the ID slug (auto-derived from --title if omitted).")
    ap.add_argument("--tier", default="T3", choices=NEWS_TIERS,
                    help="Evidence tier: T3=verifiable public source, T4=unverified (default T3).")
    ap.add_argument("--confidence", type=int, default=60,
                    help="Confidence score 0-100 (default 60 for T3 news source).")
    ap.add_argument("--link-asset", nargs="*", default=[],
                    help="Zero or more AYL_AST_* IDs to link to this event.")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the event record without writing it.")
    args = ap.parse_args()

    row = build_event(args)

    if args.dry_run:
        print(json.dumps(row, indent=2, ensure_ascii=False))
        return 0

    out = Path(args.out)
    existing = _read_jsonl(out)
    by_id = {e["event_id"]: e for e in existing}
    is_new = row["event_id"] not in by_id
    by_id[row["event_id"]] = row
    _write_jsonl(out, list(by_id.values()))

    verb = "added" if is_new else "updated"
    print(f"{verb}: {row['event_id']} ({row['event_type']}, tier={row['evidence_tier']}) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
