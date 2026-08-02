#!/usr/bin/env python3
"""Ingest USGS annual peak streamflow and stage for Puerto Rico.

Gives the corpus a flood baseline it does not otherwise have.

Every existing hydrology vector here is recent: ``ingest_usgs_levels.py`` runs a 14-day
window, ``ingest_usgs_groundwater.py`` a year. That is enough to say a river is high
relative to its own recent tail, and not enough to say whether it is high relative to
anything that has ever happened there. The peak-flow record answers the second question:
244 PR sites, **1899 to 2025**, one maximum instantaneous value per water year.

Source: the USGS **OGC API** ``peaks`` collection (``api.waterdata.usgs.gov/ogcapi/v0``),
keyless, tier T1.

  * readings -> ``data/usgs_peaks_readings.jsonl``   (streamflow / gage_height)

No assets are emitted. Peaks are reported for stream sites ``ingest_usgs_water.py``
already owns as ``USGS_*`` rows, so these are plain foreign keys — exactly what
``ingest_usgs_samples.asset_id_for`` does for the surface sites in its basin. Re-emitting
them here would fight that script's merge, which replaces the whole ``USGS_*`` slice.

    python scripts/ingest_usgs_peaks.py                    # live, keyless
    python scripts/ingest_usgs_peaks.py --sites 50055000   # one gage
    python scripts/ingest_usgs_peaks.py --src peaks.json   # offline

Unlike ``ingest_usgs_field_measurements.py`` this needs no year slicing: the whole PR
bbox returns in a handful of pages because there is at most one row per site per year.
It also needs no ``--days``. An annual peak is a permanent historical fact; narrowing the
window would only discard record floods, so the full record is always fetched.

Qualifier handling mirrors the field-measurements ingest, with a wider vocabulary. USGS
publishes 17 distinct peak qualifiers for PR. Several mark the value as something other
than a directly measured annual maximum — ``ESTIMATED``, ``GREATERTHAN``,
``MAXDAILYMEAN``, ``NOTMAXGH`` — and those rows are flagged ``needs_review`` rather than
filtered, because a 1928 estimated peak is still the best record of that flood. The
context codes (``REGULATED``, ``URBAN``, ``HISTORIC``, ``EVENT``) describe the basin, not
the measurement's reliability, and pass through into ``source_ref``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from ingest_usgs_water import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN  # noqa: E402

PEAKS_URL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/peaks/items"
DEFAULT_BBOX = f"{LON_MIN},{LAT_MIN},{LON_MAX},{LAT_MAX}"
DEFAULT_LIMIT = 500
MAX_PAGES = 200
EVIDENCE_TIER = "T1"

#: USGS parameter code -> the closed monitoring_reading.metric value it belongs to.
#: A peak is still a discharge or a stage; what makes it a peak is that it is the annual
#: maximum, which `source_ref` and the water year record.
PEAK_METRICS: dict[str, str] = {
    "00060": "streamflow",
    "00065": "gage_height",
}

#: Qualifiers meaning the published value is NOT a directly measured annual maximum.
#: Flagged, never filtered — an estimated 1928 peak is still the best record of that
#: flood. Everything else USGS publishes for PR (REGULATED, URBAN, HISTORIC, EVENT,
#: REVISED, BACKWATER, DATUMCHANGE, DIFFDATUM, GHNOTASSCPKQ, UNKNOWNREGULATION,
#: MONTHUNKNOWN, DAYUNKNOWN) describes the basin or the date, not the value's fidelity.
_VALUE_CAVEAT_QUALIFIERS = frozenset({
    "ESTIMATED",      # discharge estimated rather than measured
    "GREATERTHAN",    # actual peak exceeded the published value
    "LESSTHAN",       # actual peak was below the published value
    "MAXDAILYMEAN",   # a daily mean, not an instantaneous peak
    "NOTMAXGH",       # not the maximum gage height for the year
})


def _confidence(has_coords: bool, provisional: bool = False) -> int:
    try:
        from aguayluz.confidence import score

        base = int(score(EVIDENCE_TIER, has_coords=has_coords))
    except Exception:  # noqa: BLE001
        base = 80 if has_coords else 65
    return max(0, base - (5 if provisional else 0))


# ── source acquisition ────────────────────────────────────────────────────────
def fetch_peaks_live(
    *,
    bbox: str = DEFAULT_BBOX,
    sites: tuple[str, ...] | list[str] = (),
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """Paginated GeoJSON pages from the peaks collection."""
    import httpx

    docs: list[dict] = []
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        offset = 0
        for _ in range(MAX_PAGES):
            params: list[tuple[str, str]] = [
                ("f", "json"), ("limit", str(limit)), ("offset", str(offset)),
            ]
            if sites:
                params += [("monitoring_location_id", f"USGS-{s}") for s in sites]
            else:
                params.append(("bbox", bbox))
            r = client.get(PEAKS_URL, params=params)
            r.raise_for_status()
            doc = r.json()
            docs.append(doc)
            if len(doc.get("features") or []) < limit:
                break
            offset += limit
    return docs


# ── build rows ────────────────────────────────────────────────────────────────
def _site_no(monitoring_location_id: Any) -> str:
    return str(monitoring_location_id or "").split("-", 1)[-1].strip()


def asset_id_for(site_no: str) -> str:
    """Foreign key into the ``USGS_*`` assets ``ingest_usgs_water.py`` maintains.

    This script owns no assets, so it never writes one — asset merges never touch
    readings, which is what makes a cross-script reference safe here.
    """
    return f"USGS_{site_no}"


def _qualifiers(props: dict) -> list[str]:
    raw = props.get("qualifier")
    if not raw:
        return []
    items = [raw] if isinstance(raw, str) else list(raw)
    return sorted({str(q).strip() for q in items if str(q).strip()})


def _needs_review(quals: list[str]) -> bool:
    return any(q.upper() in _VALUE_CAVEAT_QUALIFIERS for q in quals)


def build_readings(docs: Any) -> tuple[list[dict], dict[str, int]]:
    """Annual peaks -> monitoring_reading rows, plus a count of what was dropped."""
    from ingest_usgs_field_measurements import _observed_date, parse_features

    readings: list[dict] = []
    skipped = {"no_site": 0, "no_value": 0, "no_date": 0, "no_unit": 0,
               "unmapped_parameter": 0, "duplicate": 0}
    seen: set[str] = set()

    for feat in parse_features(docs):
        props = feat.get("properties") or {}
        site = _site_no(props.get("monitoring_location_id"))
        if not site:
            skipped["no_site"] += 1
            continue

        pcode = str(props.get("parameter_code") or "").strip()
        metric = PEAK_METRICS.get(pcode)
        if not metric:
            # A peak parameter this producer has no closed-enum home for. Counted, not
            # coerced to `other` — a mislabelled metric is worse than an absent row.
            skipped["unmapped_parameter"] += 1
            continue

        raw = str(props.get("value") or "").strip()
        if not raw:
            skipped["no_value"] += 1
            continue
        try:
            value = float(raw)
        except ValueError:
            skipped["no_value"] += 1
            continue

        day = _observed_date(props)
        if not day:
            skipped["no_date"] += 1
            continue

        unit = str(props.get("unit_of_measure") or "").strip()
        if not unit:
            skipped["no_unit"] += 1
            continue

        water_year = props.get("water_year")
        quals = _qualifiers(props)

        # "One peak per site, parameter and water year" is WRONG, and assuming it drops
        # real data. For stage, USGS publishes two rows for the same year — and 12 times
        # in the PR record, for the same DAY:
        #   NOTMAXGH      the stage that accompanied the peak DISCHARGE
        #   GHNOTASSCPKQ  the year's maximum stage, which occurred at some other flow
        # At site 50055225 in water year 1996 those are 23.89 ft and 30.10 ft — six feet
        # apart, both true, and collapsing them would silently delete the higher one.
        # So the qualifier set is part of the identity. `value` is excluded, so a USGS
        # revision replaces the row instead of adding one.
        digest = hashlib.sha256(
            f"{site}|{water_year}|{pcode}|{day}|{'/'.join(quals)}".encode()
        ).hexdigest()[:8]
        reading_id = f"AYL_RDG_{day.replace('-', '')}_{site}_pk{pcode}.wy{water_year}.{digest}"
        if reading_id in seen:
            skipped["duplicate"] += 1
            continue
        seen.add(reading_id)

        qual_note = f"; qualifiers {'/'.join(quals)}" if quals else ""
        readings.append({
            "reading_id": reading_id,
            "asset_id": asset_id_for(site),
            "site_no": site,
            "metric": metric,
            "parameter_code": pcode,
            "value": value,
            "unit": unit,
            "observed_date": day,
            "provisional": False,
            "source_ref": (
                f"USGS OGC API peaks, site {site} parm {pcode}; annual maximum for water "
                f"year {water_year}{qual_note}"
            ),
            "source_hash": hashlib.sha256(
                f"{site}|{water_year}|{pcode}|{day}|{value}|{unit}|{'/'.join(quals)}".encode()
            ).hexdigest(),
            "evidence_tier": EVIDENCE_TIER,
            "confidence": _confidence(True, _needs_review(quals)),
            "review_status": "needs_review" if _needs_review(quals) else "accepted",
        })
    return readings, skipped


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge_readings(existing: list[dict], new: list[dict]) -> list[dict]:
    by_id = {r["reading_id"]: r for r in existing}
    for r in new:
        by_id[r["reading_id"]] = r
    return sorted(
        by_id.values(), key=lambda r: (r["asset_id"], r["observed_date"], r["reading_id"])
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--sites", nargs="*", default=[],
                    help="NWIS site numbers (default: every PR site in the bbox).")
    ap.add_argument("--bbox", default=DEFAULT_BBOX, help="minlon,minlat,maxlon,maxlat.")
    ap.add_argument("--src", type=Path, help="Local peaks GeoJSON (offline).")
    ap.add_argument("--out", default="data/usgs_peaks_readings.jsonl")
    args = ap.parse_args()

    if args.src:
        docs: Any = json.loads(args.src.read_text())
        origin = str(args.src)
    else:
        try:
            docs = fetch_peaks_live(bbox=args.bbox, sites=tuple(args.sites))
        except Exception as e:  # noqa: BLE001
            print(f"peaks fetch failed ({e}); pass --src <geojson> to run offline",
                  file=sys.stderr)
            return 1
        origin = "live USGS OGC peaks"

    readings, skipped = build_readings(docs)
    if not readings:
        print("no annual peaks returned; nothing to do")
        return 0

    path = REPO / args.out
    combined = merge_readings(_read_jsonl(path), readings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in combined))

    years = sorted({r["source_ref"].rsplit("water year ", 1)[-1][:4] for r in readings})
    print(f"source: {origin}")
    print(f"wrote {len(readings)} annual peak(s) ({len(combined)} total) -> {path}")
    print(f"  {len({r['site_no'] for r in readings})} site(s), water years {years[0]}..{years[-1]}")
    dropped = ", ".join(f"{k}={v}" for k, v in skipped.items() if v)
    if dropped:
        print(f"  skipped: {dropped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
