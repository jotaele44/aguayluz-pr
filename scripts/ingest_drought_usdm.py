#!/usr/bin/env python3
"""Ingest the U.S. Drought Monitor (USDM) weekly drought classification for Puerto Rico.

Fills the *drought* gap flagged in ``config/alert_modules.yaml``'s WEATHER_HAZARD
notes ("Flood, drought, rainfall, landslide risk, reservoir operations") — until now
nothing ingested drought conditions at all. ``drought.gov/states/puerto-rico`` is a
human-rendered dashboard, not a machine-readable feed, so this ingests the actual data
behind it instead: the USDM Data Services CountyStatistics API
(``usdmdataservices.unl.edu``), produced by NDMC/UNL in partnership with NOAA/USDA — a
federal T1, keyless feed, updated weekly (Thursdays).

One HTTP call fetches every PR municipio at once (``aoi=PR`` returns all 78 county-
equivalents in a single response, confirmed live — no per-municipio pagination needed),
covering ``--weeks`` of history ending today. Response is CSV:
``MapDate,FIPS,County,State,None,D0,D1,D2,D3,D4,ValidStart,ValidEnd,StatisticFormatID``.
The ``None``/``D0``..``D4`` columns are USDM's standard *cumulative* "at least this
category" percentages of municipio area (e.g. ``D1=58.45`` means 58.45% of the
municipio is in at least moderate drought, not exactly 58.45%) — never mutually
exclusive bins.

Each municipio-week is reduced to ONE reading: the *worst* category with any nonzero
area share (:func:`dominant_class`). This is the same "county is in Dx" convention
USDM/drought.gov use when coloring a single area on the map — not a fabricated
threshold, just picking the driest official band actually present. Encoded as an
ordinal 0-4 (D0..D4) with -1 for "no drought" (every category at 0%), since
``monitoring_reading.schema.json``'s ``value`` is a plain number and there is no room
in that closed schema for all six percentages per row.

PR's 78 municipio names are matched verbatim against ``data/geo/pr_municipios.json``
(already the repo's municipio centroid registry, reused rather than duplicated) via a
static name->FIPS table sourced from the Census Gazetteer county file — the same
source ``pr_municipios.json`` itself cites. One municipio-area asset is minted per
municipio (asset_id ``USDM_<fips>``), mirroring how ``ingest_noaa_tides.py`` mints one
tide-gauge asset per station.

    python scripts/ingest_drought_usdm.py --weeks 52     # live, keyless
    python scripts/ingest_drought_usdm.py --src usdm_pr_sample.csv --weeks 52
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

USDM_URL = "https://usdmdataservices.unl.edu/api/CountyStatistics/GetDroughtSeverityStatisticsByAreaPercent"

#: PR municipio name (matching data/geo/pr_municipios.json exactly) -> county FIPS.
#: Sourced from the 2023 Census Gazetteer counties file (USPS=='PR'), the same public
#: source pr_municipios.json's own docstring cites — verified to match its 78 names
#: 1:1 (no drift) before being hand-transcribed here.
PR_MUNICIPIO_FIPS: dict[str, str] = {
    "Adjuntas": "72001", "Aguada": "72003", "Aguadilla": "72005", "Aguas Buenas": "72007",
    "Aibonito": "72009", "Añasco": "72011", "Arecibo": "72013", "Arroyo": "72015",
    "Barceloneta": "72017", "Barranquitas": "72019", "Bayamón": "72021", "Cabo Rojo": "72023",
    "Caguas": "72025", "Camuy": "72027", "Canóvanas": "72029", "Carolina": "72031",
    "Cataño": "72033", "Cayey": "72035", "Ceiba": "72037", "Ciales": "72039",
    "Cidra": "72041", "Coamo": "72043", "Comerío": "72045", "Corozal": "72047",
    "Culebra": "72049", "Dorado": "72051", "Fajardo": "72053", "Florida": "72054",
    "Guánica": "72055", "Guayama": "72057", "Guayanilla": "72059", "Guaynabo": "72061",
    "Gurabo": "72063", "Hatillo": "72065", "Hormigueros": "72067", "Humacao": "72069",
    "Isabela": "72071", "Jayuya": "72073", "Juana Díaz": "72075", "Juncos": "72077",
    "Lajas": "72079", "Lares": "72081", "Las Marías": "72083", "Las Piedras": "72085",
    "Loíza": "72087", "Luquillo": "72089", "Manatí": "72091", "Maricao": "72093",
    "Maunabo": "72095", "Mayagüez": "72097", "Moca": "72099", "Morovis": "72101",
    "Naguabo": "72103", "Naranjito": "72105", "Orocovis": "72107", "Patillas": "72109",
    "Peñuelas": "72111", "Ponce": "72113", "Quebradillas": "72115", "Rincón": "72117",
    "Río Grande": "72119", "Sabana Grande": "72121", "Salinas": "72123", "San Germán": "72125",
    "San Juan": "72127", "San Lorenzo": "72129", "San Sebastián": "72131", "Santa Isabel": "72133",
    "Toa Alta": "72135", "Toa Baja": "72137", "Trujillo Alto": "72139", "Utuado": "72141",
    "Vega Alta": "72143", "Vega Baja": "72145", "Vieques": "72147", "Villalba": "72149",
    "Yabucoa": "72151", "Yauco": "72153",
}
FIPS_TO_MUNICIPIO: dict[str, str] = {v: k for k, v in PR_MUNICIPIO_FIPS.items()}

#: Ascending USDM severity bands. Index doubles as the ordinal encoding (D0=0..D4=4).
D_LEVELS: tuple[str, ...] = ("D0", "D1", "D2", "D3", "D4")


def _confidence(has_coords: bool = True) -> int:
    try:
        from aguayluz.confidence import score

        return int(score("T1", has_coords=has_coords))
    except Exception:  # noqa: BLE001
        return 80 if has_coords else 65


# ── source acquisition ────────────────────────────────────────────────────────
def fetch_live(start: date, end: date) -> str:
    """One request returns every PR municipio for the whole date range as CSV."""
    import httpx

    params = {
        "aoi": "PR",
        "startdate": f"{start.month}/{start.day}/{start.year}",
        "enddate": f"{end.month}/{end.day}/{end.year}",
        "statisticsType": "1",
    }
    r = httpx.get(USDM_URL, params=params, timeout=120)
    r.raise_for_status()
    return r.text


def parse_rows(csv_text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(csv_text)))


# ── classification ──────────────────────────────────────────────────────────
def dominant_class(row: dict[str, str]) -> tuple[int, str]:
    """Worst USDM category with any nonzero area share; -1/"None" if the municipio
    has no drought designation at all this week. Mirrors how USDM/drought.gov color a
    single area on the map — the "at least" percentages are cumulative, so the highest
    nonzero level is the map's actual category, not an invented threshold."""
    worst_ordinal = -1
    worst_label = "None"
    for ordinal, level in enumerate(D_LEVELS):
        raw = (row.get(level) or "0").replace(",", "").strip()
        try:
            pct = float(raw)
        except ValueError:
            continue
        if pct > 0:
            worst_ordinal = ordinal
            worst_label = level
    return worst_ordinal, worst_label


def _municipio_name(county_field: str) -> str:
    return county_field.removesuffix(" Municipio").strip()


# ── build asset + reading rows ─────────────────────────────────────────────
def load_municipio_geo(geo_path: Path) -> dict[str, dict[str, Any]]:
    if not geo_path.is_file():
        return {}
    doc = json.loads(geo_path.read_text())
    return {m["name"]: m for m in doc.get("municipios", []) if m.get("name")}


def build_asset(fips: str, name: str, geo: dict[str, dict[str, Any]]) -> dict:
    rec = geo.get(name) or {}
    lat, lon = rec.get("lat"), rec.get("lon")
    has_coords = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
    row = {
        "asset_id": f"USDM_{fips}",
        "asset_name": f"{name} (USDM drought monitoring area)",
        "asset_type": "water",
        "asset_subtype": "drought_monitoring_area",
        "operator": "NDMC/USDM (NOAA/USDA partnership)",
        "municipality": name,
        "geometry_type": "polygon" if has_coords else "unknown",
        "status": "active",
        "source_ref": "USDM Data Services CountyStatistics API",
        "evidence_tier": "T1",
        "confidence": _confidence(has_coords),
        "review_status": "accepted",
    }
    if has_coords:
        row["lat"], row["lon"] = round(float(lat), 6), round(float(lon), 6)
    return row


def build_reading(row: dict[str, str]) -> dict | None:
    fips = str(row.get("FIPS") or "").strip()
    name = FIPS_TO_MUNICIPIO.get(fips) or _municipio_name(str(row.get("County") or ""))
    if not fips or name not in PR_MUNICIPIO_FIPS:
        return None
    ordinal, label = dominant_class(row)
    observed = str(row.get("ValidStart") or "")[:10]
    mapdate = "".join(ch for ch in str(row.get("MapDate") or "") if ch.isdigit())[:8]
    if len(mapdate) != 8 or len(observed) != 10:
        return None
    return {
        "reading_id": f"AYL_RDG_{mapdate}_{fips}_drought",
        "asset_id": f"USDM_{fips}",
        "site_no": fips,
        "metric": "drought_category",
        "parameter_code": label,
        "value": float(ordinal),
        "unit": "category",
        "observed_date": observed,
        "provisional": True,
        "source_ref": "USDM CountyStatistics API (weekly D0-D4 classification, worst nonzero band)",
        "evidence_tier": "T1",
        "confidence": _confidence(True),
        "review_status": "accepted",
    }


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge_assets(existing: list[dict], drought_assets: list[dict]) -> list[dict]:
    by_id = {r["asset_id"]: r for r in existing if not str(r.get("asset_id", "")).startswith("USDM_")}
    for r in drought_assets:
        by_id[r["asset_id"]] = r
    return list(by_id.values())


def merge_readings(existing: list[dict], new: list[dict]) -> list[dict]:
    by_id = {r["reading_id"]: r for r in existing}
    for r in new:
        by_id[r["reading_id"]] = r
    return sorted(by_id.values(), key=lambda r: (r["asset_id"], r["observed_date"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, help="Local CSV file (offline/fixture mode).")
    ap.add_argument("--assets-out", default="data/utility_assets.jsonl")
    ap.add_argument("--readings-out", default="data/drought_conditions.jsonl")
    ap.add_argument("--geo", default="data/geo/pr_municipios.json")
    ap.add_argument("--weeks", type=int, default=52, help="Weeks of history to fetch (one call covers all).")
    args = ap.parse_args()

    if args.src:
        csv_text = args.src.read_text()
        origin = str(args.src)
    else:
        end = date.today()
        start = end - timedelta(weeks=args.weeks)
        try:
            csv_text = fetch_live(start, end)
        except Exception as e:  # noqa: BLE001
            print(f"live USDM fetch failed ({e}); pass --src <csv> to run offline", file=sys.stderr)
            return 1
        origin = f"live USDM CountyStatistics (aoi=PR, {args.weeks}w)"

    rows = parse_rows(csv_text)
    geo = load_municipio_geo(REPO / args.geo)

    seen_fips = {str(r.get("FIPS") or "").strip() for r in rows}
    assets = [
        build_asset(fips, FIPS_TO_MUNICIPIO[fips], geo)
        for fips in sorted(seen_fips)
        if fips in FIPS_TO_MUNICIPIO
    ]
    readings = [r for r in (build_reading(row) for row in rows) if r is not None]

    apath = REPO / args.assets_out
    combined_assets = merge_assets(_read_jsonl(apath), assets)
    apath.parent.mkdir(parents=True, exist_ok=True)
    apath.write_text("".join(json.dumps(r) + "\n" for r in combined_assets))

    rpath = REPO / args.readings_out
    combined_readings = merge_readings(_read_jsonl(rpath), readings)
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text("".join(json.dumps(r) + "\n" for r in combined_readings))

    print(f"source: {origin}")
    print(f"parsed {len(rows)} municipio-week row(s) across {len(seen_fips)} municipio(s)")
    print(f"wrote {len(assets)} drought-monitoring-area assets -> {apath}")
    print(f"wrote {len(readings)} drought readings -> {rpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
