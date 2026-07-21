#!/usr/bin/env python3
"""Ingest EPA ECHO Clean Water Act enforcement actions for PR into service_events.jsonl.

Complements ingest_sdwis_violations.py (Safe Drinking Water Act). ECHO CWA covers
Puerto Rico NPDES-permitted wastewater facilities — AAA treatment plants, industrial
dischargers — which are NOT in the SDWIS drinking-water feed. Facilities with formal
enforcement actions (consent orders, NOVs) or Significant Non-Complier (SNC) status
become service_event rows at event_type=water_quality_violation, evidence_tier=T1.

Source: EPA ECHO CWA REST services (no auth required):
  https://echodata.epa.gov/echo/cwa_rest_services.get_facilities?p_st=PR&output=JSON
  (the REST services moved off echo.epa.gov, which now 404s for this path)

The current API is a two-step flow — get_facilities returns a QueryID, and
get_qid (called with the same qcolumns) returns the facility rows. The
enforcement columns (CWPFormalEaCnt/CWPSNCStatus/...) are only populated when
explicitly requested via qcolumns, and dates come back as MM/DD/YYYY.

Merges idempotently into data/service_events.jsonl: existing ECHO-CWA rows are
replaced (matched by source_ref prefix), all other events are preserved.

Run:
    python scripts/ingest_echo.py          # live fetch
    python scripts/ingest_echo.py --src cwa.json  # offline from saved JSON
    python scripts/ingest_echo.py --dry-run       # print records, don't write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

ECHO_BASE = "https://echodata.epa.gov/echo/cwa_rest_services"
# Explicit result columns — the modern API returns only a minimal default set,
# so the enforcement fields must be requested by column id (per .metadata):
#   1 CWPName, 2 SourceID, 4 CWPCity, 66 CWPDateLastInspection, 97 CWPStatus,
#   98 CWPSNCStatus, 100 CWPSNCStatusDate, 114 CWPFormalEaCnt
ECHO_QCOLUMNS = "1,2,4,66,97,98,100,114"
ECHO_CWA_URL = (
    f"{ECHO_BASE}.get_facilities"
    f"?p_st=PR&p_active=Y&output=JSON&qcolumns={ECHO_QCOLUMNS}"
)
REPO = Path(__file__).resolve().parent.parent
MUNI_GEOJSON = REPO / "data" / "geo" / "pr_municipios.geojson"
SOURCE_PREFIX = "EPA ECHO CWA"
SLUG_RE = re.compile(r"[^A-Za-z0-9_-]")
# Incident types that indicate an active/open enforcement period
SNC_STATUS_ACTIVE = {"SNC", "VIOL", "QNCR"}


def _fetch_live() -> dict[str, Any]:
    """Two-step ECHO fetch: get_facilities issues a QueryID, get_qid returns rows.

    The returned document keeps the legacy shape (Results.Facilities), so
    build_events and offline --src fixtures are unaffected.
    """
    import httpx
    r = httpx.get(ECHO_CWA_URL, timeout=120, follow_redirects=True)
    r.raise_for_status()
    results = r.json().get("Results") or {}
    qid = results.get("QueryID")
    if not qid:
        # Legacy single-step response (or fixture-shaped) — pass through as-is.
        return {"Results": results}
    r2 = httpx.get(
        f"{ECHO_BASE}.get_qid?qid={qid}&pageno=1&output=JSON&qcolumns={ECHO_QCOLUMNS}",
        timeout=120, follow_redirects=True,
    )
    r2.raise_for_status()
    return r2.json()


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
    # The modern ECHO API returns US-format dates (MM/DD/YYYY) — normalize first.
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        s = f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    if "T" not in s:
        s = s[:10] + "T00:00:00"
    if not s.endswith("Z") and "+" not in s[10:]:
        s += "Z"
    return s


def _slug(text: str, maxlen: int = 40) -> str:
    return SLUG_RE.sub("-", str(text).strip())[:maxlen].strip("-")


def build_events(doc: dict[str, Any], canon: dict[str, str]) -> list[dict]:
    facilities = (doc.get("Results") or {}).get("Facilities") or []
    rows: list[dict] = []
    for f in facilities:
        source_id = (f.get("SourceID") or "").strip()
        if not source_id:
            continue
        formal_count_raw = f.get("CWPFormalEaCnt") or f.get("CWP3YrQtrP") or "0"
        try:
            formal_count = int(str(formal_count_raw).strip() or "0")
        except ValueError:
            formal_count = 0
        snc = (f.get("CWPSNCStatus") or "").strip().upper()
        if formal_count == 0 and snc not in SNC_STATUS_ACTIVE:
            continue  # no enforcement action to record
        # Legacy field names first (offline fixtures), then the modern API's
        # renamed columns (CWPSNCStatusDate/CWPDateLastInspection, CWPCity, CWPName).
        action_date_raw = (
            f.get("CWPDateLastFormalAction") or f.get("CWPStatusDate")
            or f.get("CWPSNCStatusDate") or f.get("CWPDateLastInspection") or ""
        )
        action_iso = _isodate(action_date_raw)
        day = (action_iso or "")[:10].replace("-", "")
        if len(day) != 8:
            continue  # event_id pattern requires YYYYMMDD
        city = (f.get("CityName") or f.get("CWPCity") or "").strip().title()
        muni = canon.get(_unaccent(city))
        affected = city or source_id
        name = (f.get("FacilityName") or f.get("CWPName") or source_id).strip()
        slug = _slug(f"CWA-{source_id}")
        event_id = f"AYL_EVT_{day}_{slug}"
        rows.append({
            "event_id": event_id,
            "event_type": "water_quality_violation",
            "affected_area": affected,
            "municipality": muni or None,
            "zone": None,
            "status_text": (
                f"facility={name} source_id={source_id} "
                f"formal_actions={formal_count} snc_status={snc or 'NONE'}"
            ),
            "start_time": action_iso,
            "end_time": None,
            "reported_customers_or_users": None,
            "source_ref": f"{SOURCE_PREFIX} source_id={source_id}",
            "source_hash": None,
            "evidence_tier": "T1",
            "confidence": 80,
            "review_status": "needs_review" if snc in SNC_STATUS_ACTIVE else "accepted",
            "linked_asset_ids": [],
        })
    return rows


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], echo: list[dict]) -> list[dict]:
    kept = [e for e in existing if not str(e.get("source_ref", "")).startswith(SOURCE_PREFIX)]
    by_id = {e["event_id"]: e for e in kept}
    for e in echo:
        by_id[e["event_id"]] = e
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=None,
                    help="Offline: path to a pre-downloaded ECHO CWA JSON response.")
    ap.add_argument("--out", default="data/service_events.jsonl")
    ap.add_argument("--muni-geojson", default=str(MUNI_GEOJSON))
    ap.add_argument("--dry-run", action="store_true",
                    help="Print records without writing.")
    args = ap.parse_args()

    if args.src:
        doc = json.loads(Path(args.src).read_text())
        origin = str(args.src)
    else:
        try:
            doc = _fetch_live()
            origin = ECHO_CWA_URL
        except Exception as e:  # noqa: BLE001
            print(f"live fetch failed ({e}); pass --src <cwa.json>", file=sys.stderr)
            return 1

    canon = load_muni_canonical(Path(args.muni_geojson))
    events = build_events(doc, canon)

    if args.dry_run:
        for e in events:
            print(json.dumps(e, ensure_ascii=False))
        print(f"(dry-run) {len(events)} ECHO CWA event(s) from {origin}")
        return 0

    out = Path(args.out)
    combined = merge(_read_jsonl(out), events)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))
    snc_count = sum(1 for e in events if "snc_status=NONE" not in (e.get("status_text") or ""))
    print(f"source: {origin}")
    print(f"wrote {len(events)} ECHO CWA events ({snc_count} with active SNC) -> {out}")
    print(f"  total events in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
