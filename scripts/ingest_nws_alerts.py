#!/usr/bin/env python3
"""Ingest NOAA/NWS active alerts for Puerto Rico into service_events.jsonl.

Fetches current NWS alerts (flood watches, hurricane warnings, tropical storm
advisories, storm surge) for PR from the public api.weather.gov endpoint. Alerts
that affect water infrastructure (floods, tropical systems, storm surge) become
service_event rows at evidence_tier=T1. Idempotent by NWS alert ID.

Event-type mapping:
  Flood Watch/Warning/Advisory/Statement  -> contamination_incident
  Hurricane/Tropical Storm Watch/Warning  -> service_interruption
  Storm Surge Watch/Warning               -> service_interruption
  All other Met alerts                    -> service_interruption

Only "Actual" status alerts are ingested (Test/Exercise/Draft are skipped).

Source: https://api.weather.gov/alerts/active?area=PR  (no auth required)

Merges idempotently: existing NWS rows (matched by source_ref prefix) are
replaced; all other events are preserved.

Run:
    python scripts/ingest_nws_alerts.py          # live fetch
    python scripts/ingest_nws_alerts.py --src alerts.json  # offline
    python scripts/ingest_nws_alerts.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

NWS_URL = "https://api.weather.gov/alerts/active?area=PR"
REPO = Path(__file__).resolve().parent.parent
SOURCE_PREFIX = "NWS-IDP"
SLUG_RE = re.compile(r"[^A-Za-z0-9_-]")

# NWS event name keywords → service_event event_type
_FLOOD_KEYWORDS = frozenset(["flood", "flash flood", "coastal flood", "urban"])
_SURGE_KEYWORDS = frozenset(["storm surge"])
_TROPICAL_KEYWORDS = frozenset(["hurricane", "tropical storm", "tropical depression", "typhoon"])


def _event_type(nws_event: str) -> str:
    lower = nws_event.lower()
    if any(k in lower for k in _FLOOD_KEYWORDS):
        return "contamination_incident"
    return "service_interruption"


def _slug(text: str, maxlen: int = 40) -> str:
    return SLUG_RE.sub("-", str(text).strip())[:maxlen].strip("-")


def _isodate(raw: Any) -> str | None:
    s = str(raw or "").strip()
    if not s or s.lower() in ("", "null", "none"):
        return None
    return s if ("T" in s) else (s + "T00:00:00Z")


def _fetch_live() -> dict[str, Any]:
    import httpx
    r = httpx.get(
        NWS_URL,
        headers={"User-Agent": "aguayluz-pr/0.1 (github.com/jotaele44/aguayluz-pr)"},
        timeout=60,
        follow_redirects=True,
    )
    r.raise_for_status()
    return r.json()


def build_events(doc: dict[str, Any]) -> list[dict]:
    features = doc.get("features") or []
    rows: list[dict] = []
    for feat in features:
        props = feat.get("properties") or {}
        if (props.get("status") or "").strip() != "Actual":
            continue
        alert_id = (props.get("id") or "").strip()
        if not alert_id:
            continue
        nws_event = (props.get("event") or "").strip()
        effective = _isodate(props.get("effective") or props.get("onset"))
        if not effective:
            continue
        day = effective[:10].replace("-", "")
        if len(day) != 8:
            continue
        # Build a stable slug from the numeric suffix of the NWS alert ID
        # e.g. "https://api.weather.gov/alerts/NWS-IDP-PROD-4949088-4399428"
        id_parts = re.findall(r"\d+", alert_id)
        id_slug = "-".join(id_parts[-2:]) if len(id_parts) >= 2 else _slug(alert_id)
        event_id = f"AYL_EVT_{day}_NWS-{id_slug}"
        # Affected area: use areaDesc or fallback
        area_desc = (props.get("areaDesc") or "Puerto Rico").strip()
        severity = (props.get("severity") or "").strip()
        expires = _isodate(props.get("ends") or props.get("expires"))
        rows.append({
            "event_id": event_id,
            "event_type": _event_type(nws_event),
            "affected_area": area_desc,
            "municipality": None,
            "zone": None,
            "status_text": (
                f"event={nws_event!r} severity={severity} "
                f"sender={props.get('senderName', 'NWS')!r}"
            ),
            "start_time": effective,
            "end_time": expires,
            "reported_customers_or_users": None,
            "source_ref": alert_id or NWS_URL,
            "source_hash": None,
            "evidence_tier": "T1",
            "confidence": 85,
            "review_status": "accepted",
            "linked_asset_ids": [],
        })
    return rows


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], nws: list[dict]) -> list[dict]:
    kept = [e for e in existing if not str(e.get("source_ref", "")).startswith(SOURCE_PREFIX)]
    by_id = {e["event_id"]: e for e in kept}
    for e in nws:
        by_id[e["event_id"]] = e
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=None,
                    help="Offline: path to a pre-downloaded NWS alerts JSON file.")
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
            origin = NWS_URL
        except Exception as e:  # noqa: BLE001
            print(f"live fetch failed ({e}); pass --src <alerts.json>", file=sys.stderr)
            return 1

    events = build_events(doc)

    if args.dry_run:
        for e in events:
            print(json.dumps(e, ensure_ascii=False))
        print(f"(dry-run) {len(events)} NWS alert(s) from {origin}")
        return 0

    out = Path(args.out)
    combined = merge(_read_jsonl(out), events)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))
    print(f"source: {origin}")
    print(f"wrote {len(events)} NWS alert(s) -> {out}")
    print(f"  total events in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
