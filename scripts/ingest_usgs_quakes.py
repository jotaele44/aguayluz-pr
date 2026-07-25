#!/usr/bin/env python3
"""Ingest USGS earthquakes for the Puerto Rico region into service_events.jsonl.

Fetches recent seismic events near Puerto Rico from the public, keyless USGS
FDSN event service (GeoJSON). Earthquakes in the PR bounding box at or above a
magnitude floor become service_event rows at evidence_tier=T1 — the seismic
signal for the SEISMIC_GEO alert module (reservoir/dam/pipe/karst/slope effects).
Idempotent by USGS event id.

Event-type mapping:
  Every qualifying earthquake -> service_interruption

The service_event schema has no dedicated seismic enum value; service_interruption
is the closest hazard bucket (the same choice ingest_nws_alerts.py makes for
tropical/surge alerts). Magnitude, depth and place are preserved in status_text.

Source (no auth required):
  https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&<pr bbox>

Merges idempotently: existing USGS-EQ rows (matched by source_ref prefix) are
replaced; all other events are preserved.

Run:
    python scripts/ingest_usgs_quakes.py                       # live fetch
    python scripts/ingest_usgs_quakes.py --src quakes.json     # offline
    python scripts/ingest_usgs_quakes.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SOURCE_PREFIX = "USGS-EQ"
SLUG_RE = re.compile(r"[^A-Za-z0-9_-]")

# Puerto Rico region bounding box (deg). Covers the main island, Vieques,
# Culebra, and the near-shore Puerto Rico Trench where relevant swarms occur.
PR_BBOX = {
    "minlatitude": 17.5,
    "maxlatitude": 19.0,
    "minlongitude": -68.0,
    "maxlongitude": -65.0,
}
# Magnitude floor: below ~2.5 events are numerous and rarely infrastructure-
# relevant; the 2019-2020 southwest PR sequence that damaged assets was M4+.
DEFAULT_MIN_MAGNITUDE = 2.5
# Default look-back window in days for a live fetch.
DEFAULT_DAYS = 30

FDSN_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"


def _slug(text: str, maxlen: int = 40) -> str:
    return SLUG_RE.sub("-", str(text).strip())[:maxlen].strip("-")


def _iso_from_epoch_ms(raw: Any) -> str | None:
    """USGS `time` is epoch milliseconds (UTC). Return an ISO-8601 string."""
    if raw is None:
        return None
    try:
        secs = int(raw) / 1000.0
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(secs, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_live(min_magnitude: float, days: int) -> dict[str, Any]:
    import httpx

    now = datetime.now(timezone.utc)
    params = {
        "format": "geojson",
        "orderby": "time",
        "minmagnitude": min_magnitude,
        "starttime": (now.replace(microsecond=0) - _timedelta_days(days)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        ),
        **PR_BBOX,
    }
    r = httpx.get(
        FDSN_URL,
        params=params,
        headers={"User-Agent": "aguayluz-pr/0.1 (github.com/jotaele44/aguayluz-pr)"},
        timeout=60,
        follow_redirects=True,
    )
    r.raise_for_status()
    return r.json()


def _timedelta_days(days: int):
    from datetime import timedelta

    return timedelta(days=days)


def _in_pr_bbox(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return (
        PR_BBOX["minlatitude"] <= lat <= PR_BBOX["maxlatitude"]
        and PR_BBOX["minlongitude"] <= lon <= PR_BBOX["maxlongitude"]
    )


def build_events(doc: dict[str, Any], min_magnitude: float = DEFAULT_MIN_MAGNITUDE) -> list[dict]:
    features = doc.get("features") or []
    rows: list[dict] = []
    for feat in features:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        lon = coords[0] if len(coords) >= 1 else None
        lat = coords[1] if len(coords) >= 2 else None
        depth = coords[2] if len(coords) >= 3 else None

        # Drop out-of-region features (FDSN honors the bbox, but --src fixtures
        # and rectangular-vs-actual edges mean we filter defensively).
        if not _in_pr_bbox(lat, lon):
            continue

        mag = props.get("mag")
        try:
            mag_val = float(mag)
        except (TypeError, ValueError):
            continue
        if mag_val < min_magnitude:
            continue

        usgs_id = (feat.get("id") or props.get("code") or "").strip()
        if not usgs_id:
            continue

        start_time = _iso_from_epoch_ms(props.get("time"))
        if not start_time:
            continue
        day = start_time[:10].replace("-", "")
        if len(day) != 8:
            continue

        event_id = f"AYL_EVT_{day}_USGS-EQ-{_slug(usgs_id)}"
        place = (props.get("place") or "Puerto Rico region").strip()
        depth_txt = f"{depth} km" if depth is not None else "unknown"
        rows.append({
            "event_id": event_id,
            "event_type": "service_interruption",
            "affected_area": place,
            "municipality": None,
            "zone": None,
            "status_text": (
                f"earthquake M{mag_val} depth={depth_txt} place={place!r} "
                f"source={props.get('net', 'usgs')!r}"
            ),
            "start_time": start_time,
            "end_time": None,
            "reported_customers_or_users": None,
            # Preserve the exact USGS epicenter so downstream alert promotion can link
            # by real distance instead of falling back to a municipality centroid.
            "lat": round(float(lat), 6) if isinstance(lat, (int, float)) else None,
            "lon": round(float(lon), 6) if isinstance(lon, (int, float)) else None,
            "source_ref": f"{SOURCE_PREFIX}:{usgs_id}",
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


def merge(existing: list[dict], quakes: list[dict]) -> list[dict]:
    kept = [e for e in existing if not str(e.get("source_ref", "")).startswith(SOURCE_PREFIX)]
    by_id = {e["event_id"]: e for e in kept}
    for e in quakes:
        by_id[e["event_id"]] = e
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--src", type=Path, default=None,
                    help="Offline: path to a pre-downloaded USGS FDSN GeoJSON file.")
    ap.add_argument("--out", default="data/service_events.jsonl")
    ap.add_argument("--min-magnitude", type=float, default=DEFAULT_MIN_MAGNITUDE,
                    help=f"Magnitude floor (default {DEFAULT_MIN_MAGNITUDE}).")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"Live look-back window in days (default {DEFAULT_DAYS}).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print records without writing.")
    args = ap.parse_args()

    if args.src:
        doc = json.loads(Path(args.src).read_text())
        origin = str(args.src)
    else:
        try:
            doc = _fetch_live(args.min_magnitude, args.days)
            origin = FDSN_URL
        except Exception as e:  # noqa: BLE001
            print(f"live fetch failed ({e}); pass --src <quakes.json>", file=sys.stderr)
            return 1

    events = build_events(doc, min_magnitude=args.min_magnitude)

    if args.dry_run:
        for e in events:
            print(json.dumps(e, ensure_ascii=False))
        print(f"(dry-run) {len(events)} USGS earthquake(s) from {origin}")
        return 0

    out = Path(args.out)
    combined = merge(_read_jsonl(out), events)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))
    print(f"source: {origin}")
    print(f"wrote {len(events)} USGS earthquake(s) -> {out}")
    print(f"  total events in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
