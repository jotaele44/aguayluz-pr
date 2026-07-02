#!/usr/bin/env python3
"""Ingest FEMA disaster declarations for Puerto Rico into service_events.jsonl.

Maps FEMA Major Disaster (DR) and Emergency (EM) declarations for PR to
service_event rows at event_type=project_update, evidence_tier=T1. These
declarations activate federal recovery programs (FEMA PA/IA/HM) that fund
water, wastewater, and power infrastructure repair projects.

Only infrastructure-relevant incident types are ingested:
  Hurricane, Tropical Storm, Flood, Severe Storm, Typhoon, Tsunami,
  Earthquake, Landslide, Mud/Landslide

Source: https://www.fema.gov/api/open/v2/disasterDeclarationsSummaries
        (public OData API, no auth required)

Merges idempotently: existing FEMA rows (matched by source_ref prefix "FEMA DR")
are replaced; all other events are preserved.

Run:
    python scripts/ingest_fema.py          # live fetch
    python scripts/ingest_fema.py --src fema.json  # offline
    python scripts/ingest_fema.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

FEMA_URL = (
    "https://www.fema.gov/api/open/v2/disasterDeclarationsSummaries"
    "?$filter=state eq 'PR'&$orderby=declarationDate desc&$top=200"
)
REPO = Path(__file__).resolve().parent.parent
SOURCE_PREFIX = "FEMA DR"

INFRA_INCIDENT_TYPES = frozenset({
    "Hurricane",
    "Tropical Storm",
    "Flood",
    "Severe Storm(s)",
    "Severe Storms",
    "Typhoon",
    "Tsunami",
    "Earthquake",
    "Landslide",
    "Mud/Landslide",
    "Coastal Storm",
    "Tornadoes",
})


def _fetch_live() -> dict[str, Any]:
    import httpx
    r = httpx.get(FEMA_URL, timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def _isodate(raw: Any) -> str | None:
    s = str(raw or "").strip()
    if not s or s.lower() in ("", "null", "none"):
        return None
    if "T" not in s:
        s = s[:10] + "T00:00:00Z"
    elif not s.endswith("Z") and "+" not in s[10:]:
        s += "Z" if "." not in s[19:] else ""
    return s


def build_events(doc: dict[str, Any]) -> list[dict]:
    declarations = doc.get("DisasterDeclarationsSummaries") or []
    rows: list[dict] = []
    for d in declarations:
        incident_type = (d.get("incidentType") or "").strip()
        if incident_type not in INFRA_INCIDENT_TYPES:
            continue
        disaster_num = d.get("disasterNumber")
        if not disaster_num:
            continue
        declaration_date = _isodate(d.get("declarationDate"))
        if not declaration_date:
            continue
        day = declaration_date[:10].replace("-", "")
        if len(day) != 8:
            continue
        title = (d.get("declarationTitle") or f"Disaster {disaster_num}").strip()
        disaster_type = (d.get("disasterType") or "DR").strip()
        begin = _isodate(d.get("incidentBeginDate"))
        end = _isodate(d.get("incidentEndDate"))
        closeout = _isodate(d.get("closeoutDate"))
        # Declarations with no closeout are still open / recovery ongoing
        review_status = "accepted" if closeout else "needs_review"
        pa_declared = bool(d.get("paProgramDeclared"))
        ia_declared = bool(d.get("iaProgramDeclared"))
        programs = "+".join(p for p, v in [("PA", pa_declared), ("IA", ia_declared)] if v) or "none"
        rows.append({
            "event_id": f"AYL_EVT_{day}_FEMA-{disaster_type}{disaster_num}",
            "event_type": "project_update",
            "affected_area": "Puerto Rico",
            "municipality": None,
            "zone": None,
            "status_text": (
                f"disaster={disaster_type}{disaster_num} type={incident_type!r} "
                f"title={title!r} programs={programs} "
                f"closeout={'open' if not closeout else closeout[:10]}"
            ),
            "start_time": begin or declaration_date,
            "end_time": end,
            "reported_customers_or_users": None,
            "source_ref": f"{SOURCE_PREFIX} {disaster_type}{disaster_num}",
            "source_hash": None,
            "evidence_tier": "T1",
            "confidence": 90,
            "review_status": review_status,
            "linked_asset_ids": [],
        })
    return rows


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], fema: list[dict]) -> list[dict]:
    kept = [e for e in existing if not str(e.get("source_ref", "")).startswith(SOURCE_PREFIX)]
    by_id = {e["event_id"]: e for e in kept}
    for e in fema:
        by_id[e["event_id"]] = e
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=None,
                    help="Offline: path to a pre-downloaded FEMA JSON response.")
    ap.add_argument("--out", default="data/service_events.jsonl")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print records without writing.")
    args = ap.parse_args()

    if args.src:
        doc = json.loads(Path(args.src).read_text())
        origin = str(args.src)
    else:
        try:
            doc = _fetch_live()
            origin = FEMA_URL
        except Exception as e:  # noqa: BLE001
            print(f"live fetch failed ({e}); pass --src <fema.json>", file=sys.stderr)
            return 1

    events = build_events(doc)

    if args.dry_run:
        for e in events:
            print(json.dumps(e, ensure_ascii=False))
        print(f"(dry-run) {len(events)} FEMA declaration(s) from {origin}")
        return 0

    out = Path(args.out)
    combined = merge(_read_jsonl(out), events)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))
    open_count = sum(1 for e in events if e["review_status"] == "needs_review")
    print(f"source: {origin}")
    print(f"wrote {len(events)} FEMA declarations ({open_count} open/recovery) -> {out}")
    print(f"  total events in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
