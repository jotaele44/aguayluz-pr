#!/usr/bin/env python3
"""Ingest USGS discrete groundwater field measurements for Puerto Rico.

Closes the coverage hole left by the decommissioning of ``nwis/gwlevels/``.

``ingest_usgs_groundwater.py`` reads the NWIS **Daily Values** service and therefore
keeps only wells that carry a continuous series — 5,437 PR groundwater sites become 36
assets, deliberately. But most PR wells are not instrumented: a hydrographer visits a
few times a year and records a single depth-to-water. Those measurements have no daily
series, so that script cannot see them no matter how current they are.

Source: the USGS **OGC API** ``field-measurements`` collection
(``api.waterdata.usgs.gov/ogcapi/v0``), keyless, tier T1. This is the successor to
``waterservices.usgs.gov/nwis/gwlevels/``, which now returns HTTP 301 to a
decommissioning notice — the service ``ingest_usgs_groundwater.py``'s docstring warned
about. Site names come from the sibling ``monitoring-locations`` collection.

  * assets   -> ``data/utility_assets.jsonl``                      (``USGSFM_`` prefix)
  * readings -> ``data/usgs_field_measurements_readings.jsonl``    (groundwater_level)

The ``*_readings.jsonl`` suffix is load-bearing: ``scripts/federation_export.py`` globs
``data/*_readings.jsonl``, so this reaches the canonical export with no exporter change.

    python scripts/ingest_usgs_field_measurements.py                    # live, keyless
    python scripts/ingest_usgs_field_measurements.py --days 365         # shorter window
    python scripts/ingest_usgs_field_measurements.py --sites 180046067053700
    python scripts/ingest_usgs_field_measurements.py --src fm.json --src-locations ml.json

THIS FILE MUST NOT BE ADDED TO ``scripts/build_alerts.py``.

``build_alerts.py`` reads three *explicitly named* reading files (reservoir, groundwater,
coastal); it does not glob. That is what keeps this vector out of the HYDRO_OPS aquifer
proxy, and it needs to stay that way. ``src/aguayluz/water_alerts.py`` drives
``_AQUIFER_METRICS`` with ``direction="high"`` and the caveat "deeper reading = lower
aquifer" — correct for parameter 72019 (depth *below* land surface) and **inverted** for
62610 (elevation *above* NGVD29), where a high value means more water, not less. Both
map onto the same closed-enum metric, ``groundwater_level``, so a mixed series would
also make any percentile over it meaningless.

Hence: 72019 only by default, 62610 strictly opt-in via ``--parameter-codes``.

Two fetch behaviours worth knowing before changing them:

  * **Year slicing is required, not an optimization.** A single request spanning the
    whole PR bbox and a decade is cancelled server-side with
    ``InvalidQuery: "Long running query has been cancelled."`` One year at a time
    answers in a few seconds.
  * The API returns ``value`` as a **string**, and ``time`` may carry a fabricated
    noon-UTC placeholder when ``time_of_day`` is null. The authoritative calendar date
    is the ``year``/``month``/``day`` integer triple, which is what this reads.

Deliberate refusals, same principle as ``ingest_usgs_samples.py`` — a plausible wrong
number is worse than no number:

  * a measurement with **no parseable value** is skipped, never coerced to 0.0;
  * a measurement with **no resolvable date** is skipped;
  * **negative values are kept.** A negative 72019 is a real flowing-artesian well, not
    bad data, and filtering it would delete the most hydrologically interesting rows.

All drops are counted and reported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

# Reuse the surface-water ingester's municipality resolver and PR bounds — the same
# helpers ingest_usgs_groundwater.py, ingest_neon.py and ingest_usgs_samples.py reuse.
from ingest_usgs_water import (  # noqa: E402
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    MUNI_GEOJSON,
    load_municipios,
    municipality_for,
)

OGC_ROOT = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
FIELD_MEASUREMENTS_URL = f"{OGC_ROOT}/field-measurements/items"
MONITORING_LOCATIONS_URL = f"{OGC_ROOT}/monitoring-locations/items"

#: Built from the repo's own PR bounds rather than hand-typed, so the fetch window is by
#: construction the same window build_assets accepts coordinates in.
DEFAULT_BBOX = f"{LON_MIN},{LAT_MIN},{LON_MAX},{LAT_MAX}"

#: Both codes map onto this one closed-enum value; `parameter_code` is what keeps them
#: distinguishable downstream.
GW_METRIC = "groundwater_level"

#: 72019 ONLY by default. See the module docstring: 62610 runs in the opposite direction
#: and must never be mixed into an aquifer-drawdown series by accident.
DEFAULT_PARAMETER_CODES: tuple[str, ...] = ("72019",)
PARAM_NOTES: dict[str, str] = {
    "72019": "depth to water level below land surface",
    "62610": "groundwater level above NGVD 1929",
}

#: Ten years is the shortest window that brackets both events dominating PR aquifer
#: interpretation — Hurricane Maria (2017-09) and the Dec-2019/Jan-2020 southwest
#: earthquake sequence. At 2-4 visits per well per year, a 365-day window yields 2-4
#: points per well: enough to plot nothing.
DEFAULT_DAYS = 3650
DEFAULT_LIMIT = 500
#: A runaway-loop backstop, not an expectation. 500 pages x 500 = 250k features.
MAX_PAGES_PER_SLICE = 500
EVIDENCE_TIER = "T1"

#: Every well this script touches gets the ``USGSFM_`` prefix, including the ~34 that
#: ALSO exist as ``USGSGW_`` rows. Two asset rows for one well is a real cost, paid
#: deliberately.
#:
#: The alternative — routing the overlap's readings at ``USGSGW_`` — makes this script's
#: primary key a function of ``ingest_usgs_groundwater``'s most recent output. That
#: script keeps only wells with a live daily-values series and REPLACES the whole
#: ``USGSGW_`` slice on every daily run. A well that drops out of DV coverage — the exact
#: trend this collection documents — would take its asset with it and orphan every
#: reading already written against it, then reappear here under a second id on the next
#: run. The id would flip-flop, driven by a sibling's cadence.
#:
#: Disjoint namespaces make the two cadences order-independent, which is the whole point.
#: Same fix the repo already applied twice: ``USGS_`` -> ``USGSGW_`` -> ``USGSWQ_``.
FM_PREFIX = "USGSFM_"


def asset_id_for(site_no: str) -> str:
    """Asset id for a field-measurement well. A pure function of the site number."""
    return f"{FM_PREFIX}{site_no}"


def _confidence(has_coords: bool, provisional: bool = False) -> int:
    try:
        from aguayluz.confidence import score

        base = int(score(EVIDENCE_TIER, has_coords=has_coords))
    except Exception:  # noqa: BLE001
        base = 80 if has_coords else 65
    return max(0, base - (5 if provisional else 0))


# ── source acquisition ────────────────────────────────────────────────────────
def _year_slices(start: str, end: str) -> list[tuple[str, str]]:
    """Split an ISO date range into calendar-year chunks.

    Required, not an optimization: the API cancels a whole-bbox decade-wide query with
    ``InvalidQuery: "Long running query has been cancelled."``
    """
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    out: list[tuple[str, str]] = []
    cur = s
    while cur < e:
        nxt = min(date(cur.year + 1, 1, 1), e)
        out.append((cur.isoformat(), nxt.isoformat()))
        cur = nxt
    return out


def year_slices(start: date, end: date) -> list[tuple[date, date]]:
    """Current-main compatibility wrapper for coverage tests.

    The durable producer uses ISO strings because they flow directly into the OGC
    ``datetime`` query. The coverage matrix tests exercise the same year-boundary
    behavior with ``date`` objects, so keep both entry points backed by one rule.
    """
    return [
        (date.fromisoformat(left), date.fromisoformat(right))
        for left, right in _year_slices(start.isoformat(), end.isoformat())
    ]


def fetch_field_measurements_live(
    *,
    bbox: str = DEFAULT_BBOX,
    parameter_codes: tuple[str, ...] | list[str] = DEFAULT_PARAMETER_CODES,
    start: str,
    end: str,
    sites: tuple[str, ...] | list[str] = (),
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """Paginated GeoJSON pages from the field-measurements collection.

    Returns raw FeatureCollection documents, one per page — the same shape a ``--src``
    file holds, so offline and live runs go through identical parsing.
    """
    import httpx

    docs: list[dict] = []
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        for pcode in parameter_codes:
            for slice_start, slice_end in _year_slices(start, end):
                offset = 0
                for _ in range(MAX_PAGES_PER_SLICE):
                    params: list[tuple[str, str]] = [
                        ("f", "json"),
                        ("parameter_code", pcode),
                        ("datetime", f"{slice_start}T00:00:00Z/{slice_end}T00:00:00Z"),
                        ("limit", str(limit)),
                        ("offset", str(offset)),
                    ]
                    if sites:
                        params += [("monitoring_location_id", f"USGS-{s}") for s in sites]
                    else:
                        params.append(("bbox", bbox))
                    r = client.get(FIELD_MEASUREMENTS_URL, params=params)
                    r.raise_for_status()
                    doc = r.json()
                    docs.append(doc)
                    if len(doc.get("features") or []) < limit:
                        break
                    offset += limit
    return docs


def fetch_live(days: int, parameter_codes: list[str], page_size: int) -> list[dict]:
    """Current-main compatibility wrapper around the certified live fetcher."""
    end = datetime.now(timezone.utc).date().isoformat()
    start = (date.fromisoformat(end) - timedelta(days=max(1, days))).isoformat()
    return fetch_field_measurements_live(
        parameter_codes=tuple(parameter_codes),
        start=start,
        end=end,
        limit=page_size,
    )


def fetch_locations_live(
    *,
    bbox: str = DEFAULT_BBOX,
    sites: tuple[str, ...] | list[str] = (),
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """Site metadata from the monitoring-locations collection.

    Needed, not garnish: field-measurements carries no site name, and
    ``utility_asset.asset_name`` is required with ``minLength: 1``.
    """
    import httpx

    docs: list[dict] = []
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        if sites:
            # One request per site: unlike field-measurements, this collection does NOT
            # accept a repeated `id` — it silently honours only the last value and
            # returns a single feature, which would leave every other site unnamed.
            for site in sites:
                r = client.get(
                    MONITORING_LOCATIONS_URL, params={"f": "json", "id": f"USGS-{site}"}
                )
                r.raise_for_status()
                docs.append(r.json())
            return docs

        offset = 0
        for _ in range(MAX_PAGES_PER_SLICE):
            params = {
                "f": "json",
                "bbox": bbox,
                "site_type_code": "GW",
                "limit": str(limit),
                "offset": str(offset),
            }
            r = client.get(MONITORING_LOCATIONS_URL, params=params)
            r.raise_for_status()
            doc = r.json()
            docs.append(doc)
            if len(doc.get("features") or []) < limit:
                break
            offset += limit
    return docs


# ── parsing ───────────────────────────────────────────────────────────────────
def parse_features(docs: Any) -> list[dict]:
    """Flatten paginated FeatureCollections into a flat list of GeoJSON features."""
    if isinstance(docs, dict):
        docs = [docs]
    out: list[dict] = []
    for doc in docs or []:
        if isinstance(doc, list):
            out.extend(f for f in doc if isinstance(f, dict))
        elif isinstance(doc, dict):
            out.extend(f for f in (doc.get("features") or []) if isinstance(f, dict))
    return out


def parse_locations(docs: Any) -> dict[str, dict]:
    """``{site_no: {name, lat, lon, site_type_code, altitude, ...}}``, bare site keys."""
    out: dict[str, dict] = {}
    for feat in parse_features(docs):
        props = feat.get("properties") or {}
        site = _site_no(props.get("monitoring_location_number") or props.get("id") or "")
        if not site:
            continue
        lat, lon = _geometry_coords(feat)
        out[site] = {
            "name": (props.get("monitoring_location_name") or "").strip(),
            "site_type_code": (props.get("site_type_code") or "").strip(),
            "county_name": (props.get("county_name") or "").strip(),
            "altitude": props.get("altitude"),
            "vertical_datum": (props.get("vertical_datum") or "").strip(),
            "well_constructed_depth": props.get("well_constructed_depth"),
            "aquifer_code": props.get("aquifer_code"),
            "lat": lat,
            "lon": lon,
        }
    return out


def _site_no(monitoring_location_id: Any) -> str:
    return str(monitoring_location_id or "").split("-", 1)[-1].strip()


def _observed_date(props: dict) -> str | None:
    """Calendar date of the measurement.

    From the ``year``/``month``/``day`` integers, NOT ``time[:10]``. When ``time_of_day``
    is null the API fills ``time`` with a fabricated 12:00 UTC placeholder; slicing that
    can shift a UTC-4 measurement onto the wrong calendar day.
    """
    y, m, d = props.get("year"), props.get("month"), props.get("day")
    if all(isinstance(v, int) for v in (y, m, d)):
        try:
            return date(int(y), int(m), int(d)).isoformat()  # type: ignore[arg-type]
        except ValueError:
            pass
    raw = str(props.get("time") or "")[:10]
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return raw
    return None


def _clock(props: dict) -> str:
    """Time of day, only when the API actually reported one."""
    tod = props.get("time_of_day")
    return str(tod).strip()[:8] if tod else ""


#: USGS groundwater-level status qualifiers that describe a CLEAN static water level.
#:
#: Deliberately an allowlist of one. Across 648 live PR measurements the only qualifier
#: that appears is ``Static`` — and a static level is the condition you want, not a
#: caveat, so flagging it would mark 100% of the corpus for review and mean nothing.
#: The inverse rule (a denylist of bad statuses) would require this producer to hold
#: USGS's full status vocabulary and decide which entries invalidate a level. It does
#: not hold it. So: what is known to be clean passes, and anything unrecognised —
#: ``Pumping``, ``Recently pumped``, ``Above``, ``Dry``, ``Flowing``, or a value not yet
#: seen — is flagged rather than guessed at.
_CLEAN_QUALIFIERS = frozenset({"static"})


def _qualifiers(props: dict) -> list[str]:
    raw = props.get("qualifier")
    if not raw:
        return []
    items = [raw] if isinstance(raw, str) else list(raw)
    return sorted({str(q).strip() for q in items if str(q).strip()})


def _needs_review(quals: list[str]) -> bool:
    """True when any qualifier is not a known-clean static-level status."""
    return any(q.lower() not in _CLEAN_QUALIFIERS for q in quals)


def _geometry_coords(feature: dict) -> tuple[float | None, float | None]:
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") if isinstance(geom, dict) else None
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None, None
    try:
        lon, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        return None, None
    if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
        return round(lat, 6), round(lon, 6)
    return None, None


def _coords(feature: dict, loc: dict | None) -> tuple[float | None, float | None]:
    lat, lon = _geometry_coords(feature)
    if lat is not None:
        return lat, lon
    if loc and loc.get("lat") is not None:
        return loc["lat"], loc["lon"]
    return None, None


# ── build rows ────────────────────────────────────────────────────────────────
def build_assets(
    features: list[dict],
    locations: dict[str, dict] | None = None,
    munis: list[tuple[str, list[list]]] | None = None,
) -> list[dict]:
    """One asset per distinct well that produced at least one usable measurement.

    Emitted in sorted site-number order so a rerun over the same input is byte-identical
    regardless of API page ordering.
    """
    locations = locations or {}
    seen: dict[str, dict] = {}
    for feat in features:
        props = feat.get("properties") or {}
        site = _site_no(props.get("monitoring_location_id"))
        day = _observed_date(props)
        if not site or not day:
            continue
        rec = seen.setdefault(site, {"days": [], "codes": set(), "feature": feat})
        rec["days"].append(day)
        rec["codes"].add(str(props.get("parameter_code") or "").strip())

    out: list[dict] = []
    for site in sorted(seen):
        rec = seen[site]
        loc = locations.get(site)
        # A site that published a 72019/62610 measurement is a well by definition of the
        # parameter code, so missing location metadata is not a reason to drop it.
        if loc and loc.get("site_type_code") and not loc["site_type_code"].startswith("GW"):
            continue
        lat, lon = _coords(rec["feature"], loc)
        muni = municipality_for(lat, lon, munis) if (lat is not None and munis) else "unknown"
        name = (loc or {}).get("name") or f"USGS Well {site}"
        days = sorted(rec["days"])
        codes = ", ".join(sorted(c for c in rec["codes"] if c))
        # The schema is additionalProperties:false and has no field for altitude, well
        # depth or datum, so they ride in source_ref rather than being dropped. Adding a
        # key here would fail federation_export's per-row validation and take the whole
        # export down.
        extras = []
        if loc:
            if loc.get("altitude") is not None:
                extras.append(f"land surface {loc['altitude']} ft {loc.get('vertical_datum') or ''}".strip())
            if loc.get("well_constructed_depth") is not None:
                extras.append(f"well depth {loc['well_constructed_depth']} ft")
            extras.append(
                f"aquifer {loc['aquifer_code']}" if loc.get("aquifer_code")
                else "aquifer not assigned in USGS site metadata"
            )
        suffix = f"; {'; '.join(extras)}" if extras else ""
        asset = {
            "asset_id": asset_id_for(site),
            "asset_name": str(name).title(),
            "asset_type": "water",
            "asset_subtype": "groundwater_well",
            "operator": "USGS",
            "municipality": muni,
            "geometry_type": "point" if lat is not None else "unknown",
            "status": "active",
            "source_ref": (
                f"USGS OGC API field-measurements, monitoring location USGS-{site}; "
                f"{len(days)} discrete measurement(s) {days[0]}..{days[-1]}, "
                f"parm {codes or 'n/a'}{suffix}"
            ),
            "evidence_tier": EVIDENCE_TIER,
            "confidence": _confidence(lat is not None),
            # accepted, not needs_review: these are wells with recent measurements from
            # an active USGS program. federation_export puts every needs_review ASSET
            # into outputs/review_queue.json, and 80+ unactionable items would drown it.
            # Freshness is carried legibly by the date range in source_ref.
            "review_status": "accepted",
        }
        if lat is not None:
            asset["lat"], asset["lon"] = lat, lon
        out.append(asset)
    return out


def build_readings(features: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Field measurements -> monitoring_reading rows, plus a count of what was dropped.

    Returns ``(readings, skipped)``. Every drop is reported by the CLI, never swallowed.
    """
    readings: list[dict] = []
    skipped = {"no_site": 0, "no_value": 0, "no_date": 0, "no_unit": 0, "duplicate": 0}
    seen: set[str] = set()
    for feat in features:
        props = feat.get("properties") or {}
        site = _site_no(props.get("monitoring_location_id"))
        if not site:
            skipped["no_site"] += 1
            continue

        raw = str(props.get("value") or "").strip()
        if not raw:
            skipped["no_value"] += 1
            continue
        try:
            # Negatives are kept on purpose: a negative 72019 is a flowing artesian well.
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
            # monitoring_reading.unit requires a non-empty string.
            skipped["no_unit"] += 1
            continue

        pcode = str(props.get("parameter_code") or "").strip()
        clock = _clock(props)
        reading_type = str(props.get("reading_type") or "").strip()
        approval = str(props.get("approval_status") or "").strip()
        provisional = approval.lower() != "approved"
        quals = _qualifiers(props)
        datum = str(props.get("vertical_datum") or "").strip()
        procedure = str(props.get("observing_procedure") or "").strip()

        # (site, date, parameter_code) is NOT unique — a well can be visited more than
        # once a day, and reading_type distinguishes readings on one visit. The digest
        # deliberately EXCLUDES value, so a USGS revision replaces the row rather than
        # duplicating it, and it hashes the normalized (day, clock) so a date-only vs
        # full-timestamp representation change does not fork the id.
        digest = hashlib.sha256(
            f"{site}|{day}|{clock}|{pcode}|{reading_type}".encode()
        ).hexdigest()[:8]
        reading_id = f"AYL_RDG_{day.replace('-', '')}_{site}_fm{pcode}.{digest}"
        if reading_id in seen:
            # Genuine upstream duplicates: the same field_measurements_series_id and the
            # same value published under two field_visit_ids. Collapsing them is correct,
            # but it is counted rather than silent, so a future change in what the API
            # duplicates shows up in the run log instead of looking like an off-by-one.
            skipped["duplicate"] += 1
            continue
        seen.add(reading_id)

        qual_note = f"; qualifiers {'/'.join(quals)}" if quals else ""
        readings.append({
            "reading_id": reading_id,
            "asset_id": asset_id_for(site),
            "site_no": site,
            "metric": GW_METRIC,
            "parameter_code": pcode or None,
            "value": value,
            "unit": unit,
            "observed_date": day,
            "provisional": provisional,
            "source_ref": (
                f"USGS OGC API field-measurements, site {site} parm {pcode} "
                f"({PARAM_NOTES.get(pcode, 'field measurement')}); "
                f"reading_type={reading_type or 'n/a'}; procedure={procedure or 'n/a'}; "
                f"datum={datum or 'not reported'}; approval={approval or 'n/a'}{qual_note}"
            ),
            "source_hash": hashlib.sha256(
                f"{site}|{day}|{clock}|{pcode}|{reading_type}|{value}|{unit}|"
                f"{approval}|{'/'.join(quals)}|{datum}".encode()
            ).hexdigest(),
            "evidence_tier": EVIDENCE_TIER,
            "confidence": _confidence(True, provisional),
            # A level measured while the well is pumping is drawdown at the pump, not the
            # static water table. Only qualifiers known to describe a clean static level
            # pass; anything else is flagged, never filtered. See _CLEAN_QUALIFIERS.
            "review_status": "needs_review" if _needs_review(quals) else "accepted",
        })
    return readings, skipped


def rows_from_documents(documents: list[dict]) -> tuple[list[dict], list[dict], dict[str, int]]:
    """Current-main coverage adapter without weakening the richer producer contract."""
    features = parse_features(documents)
    rows, skipped = build_readings(features)
    skipped = dict(skipped)
    skipped["nonstatic_qualifier"] = sum(
        1
        for feat in features
        if _needs_review(_qualifiers(feat.get("properties") or {}))
    )
    assets = build_assets(features, None)
    return rows, assets, skipped


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge_assets(existing: list[dict], new: list[dict]) -> list[dict]:
    """Replace only the specific asset ids emitted this run.

    Deliberately NOT a prefix-wide replace: the well set here is a function of the
    ``--days`` window and the requested parameter codes, so a prefix-wide replace would
    delete every ``USGSFM_`` well that fell outside a narrowed window — orphaning
    readings already written against it. Readings are permanent, so assets must be too.
    """
    owned = {r["asset_id"] for r in new}
    kept = [r for r in existing if r.get("asset_id") not in owned]
    return kept + new


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
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"Look-back window in days (default {DEFAULT_DAYS}).")
    ap.add_argument("--start", help="ISO start date; overrides --days.")
    ap.add_argument("--end", help="ISO end date; defaults to today.")
    ap.add_argument("--sites", nargs="*", default=[],
                    help="NWIS site numbers (default: every PR well in the bbox).")
    ap.add_argument("--parameter-codes", nargs="*", default=list(DEFAULT_PARAMETER_CODES),
                    help="USGS parameter codes. 62610 is opt-in — see the module docstring.")
    ap.add_argument("--bbox", default=DEFAULT_BBOX, help="minlon,minlat,maxlon,maxlat.")
    ap.add_argument("--src", type=Path, help="Local field-measurements GeoJSON (offline).")
    ap.add_argument("--src-locations", type=Path,
                    help="Local monitoring-locations GeoJSON (offline).")
    ap.add_argument("--assets-out", default="data/utility_assets.jsonl")
    ap.add_argument("--readings-out", default="data/usgs_field_measurements_readings.jsonl")
    args = ap.parse_args()

    end = args.end or datetime.now(timezone.utc).date().isoformat()
    start = args.start or (
        date.fromisoformat(end) - timedelta(days=max(1, args.days))
    ).isoformat()

    if args.src:
        docs = json.loads(args.src.read_text())
        origin = str(args.src)
    else:
        try:
            docs = fetch_field_measurements_live(
                bbox=args.bbox, parameter_codes=tuple(args.parameter_codes),
                start=start, end=end, sites=tuple(args.sites),
            )
        except Exception as e:  # noqa: BLE001
            print(f"field-measurements fetch failed ({e}); pass --src <geojson> to run offline",
                  file=sys.stderr)
            return 1
        origin = f"live USGS OGC field-measurements {start}..{end} parm {','.join(args.parameter_codes)}"

    features = parse_features(docs)
    if not features:
        print(f"no field measurements returned for {start}..{end}; nothing to do")
        return 0

    if args.src_locations:
        loc_docs: Any = json.loads(args.src_locations.read_text())
    else:
        try:
            loc_docs = fetch_locations_live(bbox=args.bbox, sites=tuple(args.sites))
        except Exception as e:  # noqa: BLE001
            print(f"monitoring-locations fetch failed ({e}); site names will fall back",
                  file=sys.stderr)
            loc_docs = []
    locations = parse_locations(loc_docs)

    munis = load_municipios(MUNI_GEOJSON)
    assets = build_assets(features, locations, munis)
    readings, skipped = build_readings(features)

    apath = REPO / args.assets_out
    if assets:
        combined_assets = merge_assets(_read_jsonl(apath), assets)
        apath.parent.mkdir(parents=True, exist_ok=True)
        # Default ensure_ascii, matching how every other asset ingest writes this file.
        # Raw UTF-8 here re-encodes hundreds of accented rows into the diff.
        apath.write_text("".join(json.dumps(r) + "\n" for r in combined_assets))

    rpath = REPO / args.readings_out
    combined = merge_readings(_read_jsonl(rpath), readings)
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in combined))

    print(f"source: {origin}")
    print(f"parsed {len(features)} field measurement(s) across {len(locations)} located site(s)")
    print(f"wrote {len(assets)} well asset(s) -> {apath}")
    print(f"wrote {len(readings)} reading(s) ({len(combined)} total) -> {rpath}")
    dropped = ", ".join(f"{k}={v}" for k, v in skipped.items() if v)
    if dropped:
        print(f"  skipped: {dropped}  (unparseable/undated measurements are not stored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
