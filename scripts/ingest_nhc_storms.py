#!/usr/bin/env python3
"""Ingest NOAA/NHC active tropical cyclones affecting the Puerto Rico approach.

``config/alert_modules.yaml`` has named **NHC** a primary source for ``WEATHER_HAZARD``
since the module registry was written, alongside NWS San Juan, USGS gauges and DRNA.
NWS and USGS were wired up; NHC never was. This closes that.

The distinction from ``ingest_nws_alerts.py`` is lead time, and it is the point.
api.weather.gov publishes a watch or warning once PR is inside the forecast envelope —
typically 48 hours out. NHC publishes a storm's position, intensity and heading from
genesis, days earlier, which is the window in which reservoirs get drawn down and
generation gets staged.

Source: ``https://www.nhc.noaa.gov/CurrentStorms.json``, keyless, tier T1. Emits
``service_event`` rows, idempotent on the storm id plus its advisory number.

    python scripts/ingest_nhc_storms.py                      # live, keyless
    python scripts/ingest_nhc_storms.py --src storms.json    # offline
    python scripts/ingest_nhc_storms.py --dry-run

Two filters, both deliberate:

  * **Atlantic basin only.** Storm ids are basin-prefixed (``al``/``ep``/``cp``). At the
    time this was written the only active storm was *Genevieve* (``ep072026``) at
    23.5N 136.0W — an eastern Pacific system roughly 11,000 km from San Juan. Without the
    prefix filter it would have raised a Puerto Rico weather event.
  * **Inside the approach box.** Atlantic storms off Cabo Verde are real but not yet
    actionable for PR. WATCH_BOX spans the corridor a system actually traverses to reach
    the island; anything outside it is tracked upstream by NHC, not here.

These rows do **not** stop at service events. ``aguayluz.alert_promotion.nhc`` promotes
each one into a ``WEATHER_HAZARD`` AlertEvent, scaling severity by classification *and*
distance to the island, so a strong storm close in clears the push/SMS threshold while the
same storm 1,300 km out does not. That promoter is deliberately separate from
``alert_promotion/weather.py``, which keys on the ``event='…'`` marker only
``ingest_nws_alerts.py`` writes — see its module docstring for why the two must not be
merged. If you change ``status_text`` here, that promoter is unaffected; it reads
``source_ref``.

KNOWN LIMITATION, stated rather than papered over: ``service_event.event_type`` is a
closed enum with no member for an approaching hazard — the closest is
``service_interruption``, which is what this emits, with the classification and intensity
carried in ``status_text`` and ``source_ref``. Adding a ``hazard_advisory`` member is a
schema change that has to be coordinated with the hub, so it is out of scope here. This
follows the precedent in ``scripts/ingest_osha.py``, which emits ``unknown`` for the same
reason. The same limitation is why severity lives in the text and not in the type.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

NHC_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
SOURCE_PREFIX = "NHC-"
SLUG_RE = re.compile(r"[^A-Za-z0-9_-]")

#: Atlantic basin. Eastern/central Pacific storms never reach Puerto Rico.
ATLANTIC_PREFIX = "al"

#: The corridor an Atlantic system traverses to threaten PR: the tropical Atlantic east
#: of the Lesser Antilles, the northeastern Caribbean, and the waters immediately north.
#: Wider than the island by design — a storm 500 km out is the whole reason to look.
WATCH_LAT_MIN, WATCH_LAT_MAX = 10.0, 25.0
WATCH_LON_MIN, WATCH_LON_MAX = -75.0, -50.0

#: NHC classification codes, expanded for the human-readable status text.
CLASSIFICATIONS: dict[str, str] = {
    "TD": "Tropical Depression",
    "TS": "Tropical Storm",
    "HU": "Hurricane",
    "MH": "Major Hurricane",
    "PTC": "Potential Tropical Cyclone",
    "STD": "Subtropical Depression",
    "STS": "Subtropical Storm",
    "TY": "Typhoon",
    "PC": "Post-tropical Cyclone",
    "LO": "Low",
    "DB": "Disturbance",
}


def _slug(text: Any, maxlen: int = 40) -> str:
    return SLUG_RE.sub("-", str(text or "").strip())[:maxlen].strip("-")


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _isodate(raw: Any) -> str | None:
    s = str(raw or "").strip()
    if not s or s.lower() in ("null", "none"):
        return None
    # NHC stamps milliseconds ("2026-08-02T03:00:00.000Z"); trim to seconds.
    return re.sub(r"\.\d+Z$", "Z", s)


def is_atlantic(storm: dict) -> bool:
    return str(storm.get("id") or "").strip().lower().startswith(ATLANTIC_PREFIX)


def threatens_pr(storm: dict) -> bool:
    """True when the storm sits inside the PR approach corridor."""
    lat, lon = _num(storm.get("latitudeNumeric")), _num(storm.get("longitudeNumeric"))
    if lat is None or lon is None:
        return False
    return WATCH_LAT_MIN <= lat <= WATCH_LAT_MAX and WATCH_LON_MIN <= lon <= WATCH_LON_MAX


# ── source acquisition ────────────────────────────────────────────────────────
def fetch_live() -> dict[str, Any]:
    import httpx

    r = httpx.get(
        NHC_URL,
        headers={"User-Agent": "aguayluz-pr/0.1 (github.com/jotaele44/aguayluz-pr)"},
        timeout=60,
        follow_redirects=True,
    )
    r.raise_for_status()
    return r.json()


# ── build rows ────────────────────────────────────────────────────────────────
def build_events(doc: dict[str, Any]) -> tuple[list[dict], dict[str, int]]:
    """Active cyclones -> service_event rows, plus a count of what was filtered.

    Returns ``(events, skipped)`` with ``skipped`` counting ``other_basin``,
    ``out_of_range`` and ``no_position``. Reported by the CLI, never swallowed.
    """
    storms = (doc or {}).get("activeStorms") or []
    events: list[dict] = []
    skipped = {"other_basin": 0, "out_of_range": 0, "no_position": 0}

    for storm in storms:
        if not isinstance(storm, dict):
            continue
        storm_id = str(storm.get("id") or "").strip()
        if not storm_id:
            continue
        if not is_atlantic(storm):
            skipped["other_basin"] += 1
            continue
        lat, lon = _num(storm.get("latitudeNumeric")), _num(storm.get("longitudeNumeric"))
        if lat is None or lon is None:
            skipped["no_position"] += 1
            continue
        if not threatens_pr(storm):
            skipped["out_of_range"] += 1
            continue

        advisory = storm.get("publicAdvisory") or {}
        adv_num = str(advisory.get("advNum") or "").strip()
        issued = _isodate(advisory.get("issuance") or storm.get("lastUpdate"))
        if not issued:
            continue
        day = issued[:10].replace("-", "")
        if len(day) != 8:
            continue

        code = str(storm.get("classification") or "").strip().upper()
        name = str(storm.get("name") or "Unnamed").strip()
        kind = CLASSIFICATIONS.get(code, code or "Tropical Cyclone")
        kt = _num(storm.get("intensity"))
        pressure = _num(storm.get("pressure"))
        heading, speed = storm.get("movementDir"), _num(storm.get("movementSpeed"))

        # The advisory number is part of the id on purpose: each advisory is a distinct
        # published position, so successive advisories accumulate into a track rather than
        # overwriting one another, while a re-run of the same advisory stays idempotent.
        suffix = f"-adv{_slug(adv_num, 6)}" if adv_num else ""
        events.append({
            "event_id": f"AYL_EVT_{day}_{SOURCE_PREFIX}{_slug(storm_id, 12)}{suffix}",
            # See the module docstring: the closed enum has no member for an approaching
            # hazard. service_interruption is the honest choice; the real classification
            # is preserved verbatim below rather than encoded in the type.
            "event_type": "service_interruption",
            "affected_area": "Puerto Rico approach corridor (NHC Atlantic basin)",
            "municipality": None,
            "zone": None,
            "status_text": (
                f"{kind} {name} — {kt:.0f} kt" if kt is not None else f"{kind} {name}"
            ) + (
                f", {pressure:.0f} mb" if pressure is not None else ""
            ) + (
                f", moving {heading}deg at {speed:.0f} kt"
                if heading is not None and speed is not None else ""
            ) + f", centre {lat:.1f}, {lon:.1f}"
            + (f", advisory {adv_num}" if adv_num else ""),
            "start_time": issued,
            "end_time": None,
            "reported_customers_or_users": None,
            "source_ref": (
                f"{SOURCE_PREFIX}{storm_id} {kind} {name}; "
                f"{advisory.get('url') or NHC_URL}"
            ),
            "source_hash": None,
            "evidence_tier": "T1",
            "confidence": 85,
            "review_status": "accepted",
            "linked_asset_ids": [],
            "lat": round(lat, 4),
            "lon": round(lon, 4),
        })
    return events, skipped


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], new: list[dict]) -> list[dict]:
    """Idempotent by event_id.

    Unlike ``ingest_nws_alerts.merge``, prior NHC rows are NOT dropped wholesale: an
    advisory that has scrolled off ``CurrentStorms.json`` still happened, and the storm's
    earlier positions are the track. Only same-id rows are replaced.
    """
    by_id = {e["event_id"]: e for e in existing}
    for e in new:
        by_id[e["event_id"]] = e
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--src", type=Path, help="Local CurrentStorms.json (offline).")
    ap.add_argument("--out", default="data/service_events.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="Print, do not write.")
    args = ap.parse_args()

    if args.src:
        doc = json.loads(args.src.read_text())
        origin = str(args.src)
    else:
        try:
            doc = fetch_live()
        except Exception as e:  # noqa: BLE001
            print(f"NHC fetch failed ({e}); pass --src <json> to run offline", file=sys.stderr)
            return 1
        origin = NHC_URL

    events, skipped = build_events(doc)
    total = len((doc or {}).get("activeStorms") or [])

    print(f"source: {origin}")
    print(f"{total} active storm(s) worldwide; {len(events)} in the PR approach corridor")
    filtered = ", ".join(f"{k}={v}" for k, v in skipped.items() if v)
    if filtered:
        print(f"  filtered: {filtered}")
    for e in events:
        print(f"  {e['event_id']}  {e['status_text']}")

    if args.dry_run:
        return 0

    path = REPO / args.out
    combined = merge(_read_jsonl(path), events)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Default ensure_ascii, matching ingest_nws_alerts / ingest_usgs_quakes /
    # ingest_sdwis_violations — every writer of this file. Raw UTF-8 here re-encodes
    # ~4,900 accented municipality rows, turning a zero-event run into a whole-file diff.
    path.write_text("".join(json.dumps(r) + "\n" for r in combined))
    print(f"wrote {len(events)} event(s) ({len(combined)} total) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
