#!/usr/bin/env python3
"""Ingest PREPS portal metrics into aguayluz service_events.jsonl.

Source: the PR emergency-portal scrape (``preps_<ts>.json`` from preps_scraper.py).
Customer-without-service + reservoir metrics become schema-valid service_event rows
(``schemas/service_event.schema.json``, additionalProperties=false). Only metrics
with a non-zero interruption value emit an event.

Source data is machine-local; pass ``--src`` to override. The materialized
``data/service_events.jsonl`` IS committed (small, public-portal-derived).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_SRC = "/Users/jotaele/Documents/Data/preps_20260604_1625.json"

# PREPS slug -> (service_event.event_type, human label)
SLUG_EVENT = {
    "clientes-sin-servicio-electrico": ("outage", "Electric customers without service"),
    "clientes-sin-servicio-de-agua": ("service_interruption", "Water customers without service"),
}


def build_events(doc: dict) -> list:
    scraped = doc.get("scraped_at") or ""
    rows = []
    for r in doc.get("records", []):
        slug = r.get("slug")
        if slug not in SLUG_EVENT:
            continue
        val = r.get("value")
        if not isinstance(val, (int, float)) or val <= 0:
            continue  # only emit an event when there IS an interruption
        event_type, label = SLUG_EVENT[slug]
        date8 = scraped[:10].replace("-", "") if scraped else "00000000"
        eid = f"AYL_EVT_{date8}_{slug}"
        row = {
            "event_id": eid,
            "event_type": event_type,
            "affected_area": "Puerto Rico (island-wide)",
            "start_time": scraped or None,
            "reported_customers_or_users": int(val),
            "source_ref": r.get("url") or "https://emergencias.pr.gov/",
            "evidence_tier": "T1",
            "confidence": 90,
            "review_status": "accepted",
        }
        if not row["start_time"]:
            del row["start_time"]
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default="data/service_events.jsonl")
    args = ap.parse_args()

    doc = json.loads(Path(args.src).read_text())
    rows = build_events(doc)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"wrote {len(rows)} service events -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
