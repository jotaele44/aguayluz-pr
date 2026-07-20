#!/usr/bin/env python3
"""Ingest OSHA/DOL workplace-safety enforcement for PR into service_events.jsonl.

Complements the EPA water feeds (ingest_echo.py / ingest_sdwis_violations.py) with
the industrial/facility safety beat: OSHA inspections of Puerto Rico establishments
(manufacturing, ports, construction) that the water feeds never cover. Each PR
inspection becomes a service_event row whose status_text carries the establishment,
inspection type, NAICS and activity number; the OSHA promoter
(src/aguayluz/alert_promotion/osha.py) later turns those into INDUSTRIAL AlertEvents.

Source: DOL Open Data Portal v4 (the modern replacement for enforcedata.dol.gov):
  https://apiprod.dol.gov/v4/get/OSHA/inspection/json?filter_object=...&X-API-KEY=...
The v4 API needs a free key (250 req/hr) — set OSHA_API_KEY (or DOL_API_KEY). The
key is read from the environment only and never written to disk (G07_NO_SECRETS).

service_event.event_type has no workplace-safety value and the schema forbids extra
keys (additionalProperties:false), so OSHA specifics live in status_text and the row
uses event_type="unknown"; the promoter keys off the "OSHA ENFORCEMENT" source_ref
prefix, not the event_type.

Merges idempotently into data/service_events.jsonl: existing OSHA rows are replaced
(matched by source_ref prefix), all other events are preserved.

Run:
    python scripts/ingest_osha.py                 # live fetch (needs OSHA_API_KEY)
    python scripts/ingest_osha.py --src osha.json # offline from saved JSON
    python scripts/ingest_osha.py --state PR --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

DOL_V4_URL = "https://apiprod.dol.gov/v4/get/OSHA/inspection/json"
REPO = Path(__file__).resolve().parent.parent
MUNI_GEOJSON = REPO / "data" / "geo" / "pr_municipios.geojson"
SOURCE_PREFIX = "OSHA ENFORCEMENT"
SLUG_RE = re.compile(r"[^A-Za-z0-9_-]")
# Inspection types whose records warrant a review before acceptance (life-safety).
_REVIEW_INSP_TYPES = ("fatal", "catastrophe", "accident", "imminent")


def _resolve_api_key() -> str | None:
    """OSHA/DOL v4 key from the environment (never the repo). None disables live fetch."""
    return os.environ.get("OSHA_API_KEY") or os.environ.get("DOL_API_KEY")


def _fetch_live(state: str) -> dict[str, Any]:
    import httpx

    key = _resolve_api_key()
    if not key:
        raise RuntimeError("no OSHA_API_KEY/DOL_API_KEY set; pass --src <osha.json> for offline")
    params = {
        "limit": 1000,
        "filter_object": json.dumps(
            [{"field": "site_state", "operator": "eq", "value": state}]
        ),
    }
    # The DOL v4 gateway authenticates on the X-API-KEY header, not a query param.
    r = httpx.get(
        DOL_V4_URL, params=params, headers={"X-API-KEY": key},
        timeout=120, follow_redirects=True,
    )
    r.raise_for_status()
    return r.json()


def _unaccent(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c)
    ).strip().upper()


def load_muni_canonical(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text())
    return {
        _unaccent((f.get("properties") or {}).get("name", "")): (f.get("properties") or {}).get("name", "")
        for f in doc.get("features", [])
        if (f.get("properties") or {}).get("name")
    }


def _isodate(raw: Any) -> str | None:
    s = str(raw or "").strip()
    if not s or s.lower() in ("", "null", "none"):
        return None
    if "T" not in s:
        s = s[:10] + "T00:00:00"
    if not s.endswith("Z") and "+" not in s[10:]:
        s += "Z"
    return s


def _slug(text: str, maxlen: int = 40) -> str:
    return SLUG_RE.sub("-", str(text).strip())[:maxlen].strip("-")


def _first(rec: dict[str, Any], *keys: str) -> str:
    """First non-empty value among candidate keys (DOL field names vary by dataset)."""
    for k in keys:
        v = rec.get(k)
        if v not in (None, "", "null"):
            return str(v).strip()
    return ""


def _records(doc: Any) -> list[dict[str, Any]]:
    """Pull the record list from a DOL v4 response ({"data":[...]}) or a bare list."""
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)]
    if isinstance(doc, dict):
        data = doc.get("data")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
    return []


def build_events(doc: Any, canon: dict[str, str], state: str = "PR") -> list[dict]:
    rows: list[dict] = []
    for rec in _records(doc):
        rec_state = _first(rec, "site_state", "state", "site_st").upper()
        if state and rec_state and rec_state != state.upper():
            continue  # server filter is authoritative, but guard offline fixtures too
        activity_nr = _first(rec, "activity_nr", "insp_activity_nr", "actvty_nr")
        if not activity_nr:
            continue
        open_iso = _isodate(_first(rec, "open_date", "open_dt", "load_dt"))
        day = (open_iso or "")[:10].replace("-", "")
        if len(day) != 8:
            continue  # event_id pattern requires YYYYMMDD
        # Closure state: a state-only query returns years of history, so a closed
        # inspection must not surface as a current hazard. Carry the case-close
        # date in end_time (an existing service_event field); the promoter maps a
        # closed inspection to a non-critical alert status.
        close_iso = _isodate(_first(rec, "close_conf_date", "close_case_date", "close_out_date"))
        estab = _first(rec, "estab_name", "estab") or f"activity {activity_nr}"
        insp_type = _first(rec, "insp_type", "inspection_type") or "Unknown"
        naics = _first(rec, "naics_code", "naics")
        city = _first(rec, "site_city", "city").title()
        muni = canon.get(_unaccent(city))
        # Only open inspections of a life-safety type still warrant review; a
        # closed historical record does not.
        needs_review = close_iso is None and any(t in insp_type.lower() for t in _REVIEW_INSP_TYPES)
        status_text = (
            f"osha inspection activity_nr={activity_nr} estab='{estab}' "
            f"insp_type='{insp_type}' naics={naics or 'NA'} city='{city}' "
            f"case={'closed' if close_iso else 'open'}"
        )
        rows.append({
            "event_id": f"AYL_EVT_{day}_{_slug(f'OSHA-{activity_nr}')}",
            "event_type": "unknown",
            "affected_area": city or estab,
            "municipality": muni or None,
            "zone": None,
            "status_text": status_text,
            "start_time": open_iso,
            "end_time": close_iso,
            "reported_customers_or_users": None,
            "source_ref": f"{SOURCE_PREFIX} activity_nr={activity_nr}",
            "source_hash": None,
            "evidence_tier": "T1",
            "confidence": 85,
            "review_status": "needs_review" if needs_review else "accepted",
            "linked_asset_ids": [],
        })
    return rows


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], osha: list[dict]) -> list[dict]:
    kept = [e for e in existing if not str(e.get("source_ref", "")).startswith(SOURCE_PREFIX)]
    by_id = {e["event_id"]: e for e in kept}
    for e in osha:
        by_id[e["event_id"]] = e
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=None,
                    help="Offline: path to a pre-downloaded DOL v4 OSHA inspection JSON.")
    ap.add_argument("--state", default="PR", help="Jurisdiction filter (default PR).")
    ap.add_argument("--out", default="data/service_events.jsonl")
    ap.add_argument("--muni-geojson", default=str(MUNI_GEOJSON))
    ap.add_argument("--dry-run", action="store_true", help="Print records without writing.")
    args = ap.parse_args()

    if args.src:
        doc = json.loads(Path(args.src).read_text())
        origin = str(args.src)
    else:
        try:
            doc = _fetch_live(args.state)
            origin = DOL_V4_URL
        except Exception as e:  # noqa: BLE001
            print(f"live fetch failed ({e}); pass --src <osha.json>", file=sys.stderr)
            return 1

    canon = load_muni_canonical(Path(args.muni_geojson))
    events = build_events(doc, canon, args.state)

    if args.dry_run:
        for e in events:
            print(json.dumps(e, ensure_ascii=False))
        print(f"(dry-run) {len(events)} OSHA event(s) from {origin}")
        return 0

    out = Path(args.out)
    combined = merge(_read_jsonl(out), events)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))
    review = sum(1 for e in events if e["review_status"] == "needs_review")
    print(f"source: {origin}")
    print(f"wrote {len(events)} OSHA events ({review} needing review) -> {out}")
    print(f"  total events in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
