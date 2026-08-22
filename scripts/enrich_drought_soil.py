#!/usr/bin/env python3
"""Enrich USDM drought-monitoring-area assets with NRCS SSURGO soil properties.

Same drought-corroboration motivation as ``scripts/ingest_precip_ncei.py``, from a
different angle: the same precipitation deficit turns into visible drought stress at
very different rates depending on the soil underneath it — a shallow, low available-
water-capacity soil dries out fast; a deep, high-AWC soil buffers a dry spell far
longer. This is static reference data (soil taxonomy barely changes), so it belongs as
an *enrichment* of the existing ``USDM_<fips>`` municipio-area assets
(``scripts/ingest_drought_usdm.py``) rather than a new time-series reading — the same
role ``scripts/enrich_waters_nhd.py`` plays for NHDPlus ids, whose ``_needs_enrichment``
skip-if-already-present + mutate-in-place pattern this script mirrors.

``soilseries.sc.egov.usda.gov`` (the Official Soil Series Description "View by List"
tool) was considered and rejected: it is a legacy ASP.NET postback form with no JSON/
CSV export, so scraping it would mean simulating ``__VIEWSTATE`` postbacks — fragile
and not what a keyless-first producer should depend on. The actual structured,
keyless source for this is USDA's **Soil Data Access** (SDA,
``sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest``), a SQL-over-REST service the
NRCS itself publishes for exactly this kind of tabular soil-property query.

Two-step live query, both live-verified against real PR points before this script was
written:

1. **Point -> mukey**, one call per municipio centroid:
   ``SDA_Get_Mukey_from_intersection_with_WktWgs84('point(lon lat)')``. Deliberately
   NOT batched into one ``multipoint(...)`` call for every centroid despite that being
   possible and far cheaper (2 HTTP calls total instead of ~79): live-testing multipoint
   showed SDA returns the mukey rows **sorted by mukey value, not in input-point
   order** (three well-separated test points came back in a different order than
   submitted, and a shared mukey across two points would collapse the row count too) —
   zipping that result back onto the input point list by position would silently
   misattribute one municipio's soil to another. One call per point is unambiguous:
   each response is read before moving to the next, so there is no order to get wrong.
2. **mukey -> aggregated attributes**, ONE batched call for every distinct mukey
   collected in step 1 (safe to batch: each returned row carries its own ``mukey``
   column, so results are matched by that key, never by position):
   ``mapunit`` joined to ``muaggatt`` (NRCS's pre-computed Map Unit Aggregated
   Attributes — dominant-condition drainage class and hydrologic group, weighted-
   average available water storage — so this script does no component/horizon
   weighting of its own).

Writes back onto the matching ``USDM_<fips>`` rows in ``data/utility_assets.jsonl``:
``soil_mukey``, ``soil_series_name`` (the dominant map unit name — this is the actual
"soil series" information the OSD tool would have given, just reached through a
queryable source), ``soil_drainage_class``, ``soil_awc_cm``, ``soil_hydrologic_group``.

Keyless, no API token. Offline-safe by design, mirroring ``enrich_waters_nhd.py``: on
a network failure nothing is written and a typed ``source-unavailable`` line is
printed, so ``scripts/refresh.py`` can run this ``optional=True``.

    python scripts/enrich_drought_soil.py                 # live, keyless
    python scripts/enrich_drought_soil.py --limit 10       # cap for a quick check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
EXIT_SOURCE_UNAVAILABLE = 2


def _post_query(client: Any, sql: str) -> list[list[Any]]:
    r = client.post(SDA_URL, json={"query": sql, "format": "JSON"})
    r.raise_for_status()
    doc = r.json()
    return doc.get("Table") or []


# ── step 1: point -> mukey ────────────────────────────────────────────────────
def parse_mukey_response(rows: list[list[Any]]) -> str | None:
    """First mukey from a single-point SDA response, or None if the point misses
    every map unit (open water, out of SSURGO coverage, etc.)."""
    return str(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else None


def fetch_mukey_for_point_live(client: Any, lon: float, lat: float) -> str | None:
    sql = f"SELECT mukey FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('point({lon} {lat})')"
    return parse_mukey_response(_post_query(client, sql))


# ── step 2: mukey -> aggregated attributes ───────────────────────────────────
_ATTR_COLUMNS = ("mukey", "muname", "drclassdcd", "aws0150wta", "hydgrpdcd")


def parse_muaggatt_response(rows: list[list[Any]]) -> dict[str, dict[str, Any]]:
    """Rows keyed by their own mukey column — safe regardless of row order."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        rec = dict(zip(_ATTR_COLUMNS, row, strict=False))
        mukey = rec.get("mukey")
        if mukey is None:
            continue
        out[str(mukey)] = rec
    return out


def fetch_soil_attributes_live(client: Any, mukeys: list[str]) -> dict[str, dict[str, Any]]:
    if not mukeys:
        return {}
    in_list = ",".join(f"'{k}'" for k in mukeys)
    sql = (
        "SELECT mu.mukey, mu.muname, ma.drclassdcd, ma.aws0150wta, ma.hydgrpdcd "
        "FROM mapunit mu INNER JOIN muaggatt ma ON mu.mukey = ma.mukey "
        f"WHERE mu.mukey IN ({in_list})"
    )
    return parse_muaggatt_response(_post_query(client, sql))


# ── merge onto asset rows ────────────────────────────────────────────────────
def _needs_enrichment(a: dict[str, Any]) -> bool:
    return (
        a.get("asset_subtype") == "drought_monitoring_area"
        and a.get("soil_mukey") is None
        and isinstance(a.get("lat"), (int, float))
        and isinstance(a.get("lon"), (int, float))
    )


def merge_soil_onto_asset(asset: dict[str, Any], mukey: str | None, attrs: dict[str, Any] | None) -> bool:
    """Write soil fields onto `asset` in place. True if anything was written."""
    if mukey is None:
        return False
    asset["soil_mukey"] = mukey
    if attrs:
        if attrs.get("muname") is not None:
            asset["soil_series_name"] = str(attrs["muname"])
        if attrs.get("drclassdcd") is not None:
            asset["soil_drainage_class"] = str(attrs["drclassdcd"])
        if attrs.get("aws0150wta") is not None:
            asset["soil_awc_cm"] = float(attrs["aws0150wta"])
        if attrs.get("hydgrpdcd") is not None:
            asset["soil_hydrologic_group"] = str(attrs["hydgrpdcd"])
    return True


# ── I/O ───────────────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assets", default="data/utility_assets.jsonl")
    ap.add_argument("--limit", type=int, default=0, help="max assets to enrich this run; 0 = no cap")
    args = ap.parse_args()

    path = REPO_ROOT / args.assets
    assets = _read_jsonl(path)
    todo = [a for a in assets if _needs_enrichment(a)]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("no drought-monitoring-area assets need soil enrichment — nothing to do")
        return 0

    try:
        import httpx
    except ImportError:
        print("source-unavailable: httpx not installed", file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE

    point_mukeys: dict[str, str] = {}
    try:
        with httpx.Client(timeout=60) as client:
            for a in todo:
                try:
                    mukey = fetch_mukey_for_point_live(client, float(a["lon"]), float(a["lat"]))
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    print(f"  skip {a.get('asset_id')}: {exc}", file=sys.stderr)
                    continue
                if mukey is not None:
                    point_mukeys[str(a["asset_id"])] = mukey

            attrs_by_mukey = fetch_soil_attributes_live(client, sorted(set(point_mukeys.values())))
    except httpx.HTTPError as exc:
        print(f"source-unavailable: SDA request failed ({exc})", file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE

    enriched = 0
    for a in todo:
        mukey = point_mukeys.get(str(a["asset_id"]))
        if merge_soil_onto_asset(a, mukey, attrs_by_mukey.get(mukey) if mukey else None):
            enriched += 1

    if enriched:
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in assets))
    print(f"enriched {enriched}/{len(todo)} drought-monitoring-area assets with soil data -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
