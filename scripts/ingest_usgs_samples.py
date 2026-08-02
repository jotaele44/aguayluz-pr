#!/usr/bin/env python3
"""Ingest USGS discrete water-quality samples for the Laguna Cartagena basin (PR).

Fills a gap the daily-values ingests structurally cannot. ``ingest_usgs_water`` and
``ingest_usgs_groundwater`` both read the NWIS **Daily Values** service, and
``ingest_usgs_groundwater`` deliberately keeps only wells that carry a time series:

    # Keep only wells that actually carry a time series — an aquifer monitor cares
    # about the monitored subset, not every historical one-off measurement site.

That rule is right, and it is why 5,437 PR groundwater sites become 36 assets. But it
means a site whose entire record is *discrete field samples* is invisible to this
producer — no matter how much chemistry it holds. The Laguna Cartagena basin in
Lajas/Boquerón is exactly that case: 187 sample results across three sites, including
nutrients, metals and faecal indicator bacteria, and not one daily value among them.

Source: the USGS **samples-data** API (``api.waterdata.usgs.gov/samples-data``), keyless,
tier T1. This is the modern replacement for ``waterservices.usgs.gov/nwis/gwlevels/``,
which now returns HTTP 301 to a decommissioning notice — confirming the warning already
carried in ``ingest_usgs_groundwater.py``'s docstring.

  * assets   -> ``data/utility_assets.jsonl``          (the well, ``USGSGW_`` prefix)
  * readings -> ``data/usgs_samples_readings.jsonl``   (monitoring_reading, water_quality)

The ``*_readings.jsonl`` suffix is load-bearing: ``scripts/federation_export.py`` globs
``data/*_readings.jsonl``, so this reaches the canonical export with no exporter change,
and ``.gitignore`` keeps it uncommitted like every other time-series file.

    python scripts/ingest_usgs_samples.py                      # live, keyless
    python scripts/ingest_usgs_samples.py --sites 50129899     # a subset
    python scripts/ingest_usgs_samples.py --src samples.csv    # offline

Two deliberate refusals, both the same principle — a plausible wrong number is worse
than no number:

  * a result with **no measured value** is skipped. 41 of the 187 rows are
    ``Not Detected``; a non-detect is not a zero, and storing it as one would fabricate
    a measurement.
  * a result with **no unit** is skipped. Several characteristics publish a blank
    ``Result_MeasureUnit``; ``monitoring_reading.unit`` requires a non-empty string, and
    inventing one would mislabel the value.

Both are counted and reported, never silent.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

# Reuse the surface-water ingester's municipality resolver — the same point-in-polygon
# helper ingest_usgs_groundwater.py and ingest_neon.py reuse. No new geo code.
from ingest_usgs_water import (  # noqa: E402
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    MUNI_GEOJSON,
    load_municipios,
    municipality_for,
)

SAMPLES_URL = "https://api.waterdata.usgs.gov/samples-data/results/narrow"

#: The Laguna Cartagena basin (Lajas / Boquerón, southwestern PR). This is the basin the
#: script was built for; widen coverage by adding site numbers here or via --sites.
#:
#: Verified against NWIS: the outflow ran daily discharge for 518 days in 1984-85 and
#: stopped; the lake was sampled once in 2011-12; the well was measured twice, in 1985
#: and 1986. The basin's records are published — the monitoring lapsed.
#: See docs/LAGUNA_CARTAGENA_GAP.md.
DEFAULT_SITES: tuple[str, ...] = (
    "50129899",           # LAGUNA CARTAGENA NR BOQUERON, PR (lake)
    "50129900",           # LAGUNA CARTAGENA OUTFLOW NR BOQUERON, PR (stream)
    "180046067053700",    # LAGUNA CARTAGENA WELL, LAJAS, PR (well)
)

#: NWIS site-number prefix -> asset_id prefix, matching what each existing ingest owns.
#: A 15-digit site number is a groundwater site (USGSGW_, ingest_usgs_groundwater.py);
#: an 8-digit one is surface water (USGS_, ingest_usgs_water.py). Getting this wrong
#: would either orphan the reading or collide with another ingest's merge.
def asset_id_for(site_no: str) -> str:
    return f"USGSGW_{site_no}" if len(site_no) > 10 else f"USGS_{site_no}"


#: Every characteristic here is a chemical, physical or biological property of a water
#: sample, so they all map onto the single closed-enum value that covers them:
#: `water_quality`. WHICH property is preserved in `parameter_code` (the USGS pcode),
#: exactly as monitoring_reading.schema.json intends ("EPA contaminant code").
SAMPLE_METRIC = "water_quality"

EVIDENCE_TIER = "T1"


def _confidence(has_coords: bool = True) -> int:
    try:
        from aguayluz.confidence import score

        return int(score(EVIDENCE_TIER, has_coords=has_coords))
    except Exception:  # noqa: BLE001
        return 80 if has_coords else 65


def _slug(value: str, limit: int = 28) -> str:
    """Filesystem/id-safe slug. `reading_id` allows [A-Za-z0-9_.-] after the date."""
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    out = "".join(c.lower() if c.isalnum() else "_" for c in folded)
    return "_".join(filter(None, out.split("_")))[:limit] or "result"


# ── source acquisition ────────────────────────────────────────────────────────
def fetch_samples_live(sites: tuple[str, ...] | list[str]) -> str:
    """Fetch the narrow-profile CSV for the given NWIS site numbers."""
    import httpx

    params = [("monitoringLocationIdentifier", f"USGS-{s}") for s in sites]
    params.append(("mimeType", "text/csv"))
    r = httpx.get(SAMPLES_URL, params=params, timeout=180)
    r.raise_for_status()
    return r.text


# ── build rows ────────────────────────────────────────────────────────────────
def _site_no(location_identifier: str) -> str:
    return str(location_identifier or "").split("-", 1)[-1].strip()


def _coords(row: dict[str, str]) -> tuple[float | None, float | None]:
    try:
        la, lo = float(row["Location_Latitude"]), float(row["Location_Longitude"])
    except (KeyError, TypeError, ValueError):
        return None, None
    if LAT_MIN <= la <= LAT_MAX and LON_MIN <= lo <= LON_MAX:
        return round(la, 6), round(lo, 6)
    return None, None


def build_assets(
    rows: list[dict[str, str]], munis: list[tuple[str, list[list]]] | None = None
) -> list[dict]:
    """Asset rows for sampled sites that are wells.

    Only wells are emitted. The surface-water sites in this basin are already owned by
    ``ingest_usgs_water.py`` as ``USGS_*`` rows; re-emitting them here would fight that
    script's merge, which replaces the whole ``USGS_*`` slice on every run.
    """
    out: dict[str, dict] = {}
    for row in rows:
        if (row.get("Location_Type") or "").strip().lower() != "well":
            continue
        site_no = _site_no(row.get("Location_Identifier", ""))
        if not site_no or site_no in out:
            continue
        lat, lon = _coords(row)
        muni = municipality_for(lat, lon, munis) if (lat is not None and munis) else "unknown"
        name = (row.get("Location_Name") or f"USGS {site_no}").strip()
        asset = {
            "asset_id": asset_id_for(site_no),
            "asset_name": name.title(),
            "asset_type": "water",
            "asset_subtype": "groundwater_well",
            "operator": "USGS",
            "municipality": muni,
            "geometry_type": "point" if lat is not None else "unknown",
            "status": "active",
            "source_ref": (
                f"USGS samples-data, site {site_no}; discrete samples only — no daily-values "
                f"time series exists for this site"
            ),
            "evidence_tier": EVIDENCE_TIER,
            "confidence": _confidence(lat is not None),
            # A well whose entire record is decades-old one-off samples is a documented
            # monitoring gap, not a live feed. needs_review keeps anything downstream
            # from reading it as current.
            "review_status": "needs_review",
        }
        if lat is not None:
            asset["lat"], asset["lon"] = lat, lon
        out[site_no] = asset
    return list(out.values())


def build_readings(rows: list[dict[str, str]]) -> tuple[list[dict], dict[str, int]]:
    """Sample results -> monitoring_reading rows, plus a count of what was dropped.

    Returns ``(readings, skipped)`` where ``skipped`` counts ``no_value`` (non-detects
    and blanks) and ``no_unit``. Both are reported by the CLI rather than swallowed.
    """
    readings: list[dict] = []
    skipped = {"no_value": 0, "no_unit": 0, "no_date": 0}
    seen: set[str] = set()

    for row in rows:
        site_no = _site_no(row.get("Location_Identifier", ""))
        if not site_no:
            continue

        raw = (row.get("Result_Measure") or "").strip()
        if not raw:
            # 'Not Detected' and blanks. A non-detect is NOT a zero.
            skipped["no_value"] += 1
            continue
        try:
            value = float(raw)
        except ValueError:
            skipped["no_value"] += 1
            continue

        unit = (row.get("Result_MeasureUnit") or "").strip()
        if not unit:
            # monitoring_reading.unit requires a non-empty string; inventing one would
            # mislabel the measurement.
            skipped["no_unit"] += 1
            continue

        day = (row.get("Activity_StartDate") or "").strip()[:10]
        if len(day) != 10:
            skipped["no_date"] += 1
            continue

        characteristic = (row.get("Result_Characteristic") or "").strip() or "result"
        pcode = (row.get("USGSpcode") or "").strip() or None

        # The characteristic slug is required, not cosmetic: one site can report a dozen
        # characteristics on the same day, and an id keyed only on site+metric+date would
        # collapse them all onto one row.
        reading_id = (
            f"AYL_RDG_{day.replace('-', '')}_USGS_{site_no}_{_slug(characteristic)}"
        )
        if reading_id in seen:
            continue
        seen.add(reading_id)

        readings.append({
            "reading_id": reading_id,
            "asset_id": asset_id_for(site_no),
            "site_no": site_no,
            "metric": SAMPLE_METRIC,
            "parameter_code": pcode,
            "value": value,
            "unit": unit,
            "observed_date": day,
            "provisional": False,
            "source_ref": (
                f"USGS samples-data narrow profile, site {site_no}, {characteristic}"
            ),
            "source_hash": hashlib.sha256(
                f"{site_no}|{day}|{characteristic}|{value}|{unit}".encode()
            ).hexdigest(),
            "evidence_tier": EVIDENCE_TIER,
            "confidence": _confidence(True),
            "review_status": "accepted",
        })
    return readings, skipped


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge_assets(existing: list[dict], new: list[dict]) -> list[dict]:
    """Replace only the specific asset ids this script owns.

    Deliberately narrower than the sibling ingests' prefix-wide replacement: this script
    covers a handful of sampled sites, so wiping every ``USGSGW_*`` row would delete the
    36 monitored wells that ``ingest_usgs_groundwater.py`` owns.
    """
    owned = {r["asset_id"] for r in new}
    kept = [r for r in existing if r.get("asset_id") not in owned]
    return kept + new


def merge_readings(existing: list[dict], new: list[dict]) -> list[dict]:
    by_id = {r["reading_id"]: r for r in existing}
    for r in new:
        by_id[r["reading_id"]] = r
    return sorted(by_id.values(), key=lambda r: (r["asset_id"], r["observed_date"], r["reading_id"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", nargs="*", default=list(DEFAULT_SITES),
                    help="NWIS site numbers (default: the Laguna Cartagena basin).")
    ap.add_argument("--src", type=Path, help="Local samples-data CSV (offline).")
    ap.add_argument("--assets-out", default="data/utility_assets.jsonl")
    ap.add_argument("--readings-out", default="data/usgs_samples_readings.jsonl")
    args = ap.parse_args()

    if args.src:
        text = args.src.read_text()
        origin = str(args.src)
    else:
        try:
            text = fetch_samples_live(args.sites)
        except Exception as e:  # noqa: BLE001
            print(f"samples-data fetch failed ({e}); pass --src <csv> to run offline",
                  file=sys.stderr)
            return 1
        origin = f"live USGS samples-data ({len(args.sites)} site(s))"

    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        print(f"no sample results returned for {args.sites}; nothing to do")
        return 0

    munis = load_municipios(MUNI_GEOJSON)
    assets = build_assets(rows, munis)
    readings, skipped = build_readings(rows)

    apath = REPO / args.assets_out
    if assets:
        combined_assets = merge_assets(_read_jsonl(apath), assets)
        apath.parent.mkdir(parents=True, exist_ok=True)
        # Default ensure_ascii, matching how every other asset ingest writes this file.
        # Raw UTF-8 here re-encodes hundreds of accented rows into the diff.
        apath.write_text("".join(json.dumps(r) + "\n" for r in combined_assets))

    rpath = REPO / args.readings_out
    combined_readings = merge_readings(_read_jsonl(rpath), readings)
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in combined_readings))

    print(f"source: {origin}")
    print(f"parsed {len(rows)} sample result(s)")
    print(f"wrote {len(assets)} well asset(s) -> {apath}")
    print(f"wrote {len(readings)} reading(s) ({len(combined_readings)} total) -> {rpath}")
    dropped = ", ".join(f"{k}={v}" for k, v in skipped.items() if v)
    if dropped:
        print(f"  skipped: {dropped}  (non-detects and unitless results are not stored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
