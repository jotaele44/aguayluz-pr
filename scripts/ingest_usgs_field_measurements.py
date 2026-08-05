#!/usr/bin/env python3
"""Re-adjudicated current-main ingest for USGS OGC field measurements.

Depth-below-land-surface parameter 72019 is enabled by default. Parameter 62610,
which moves in the opposite hydrologic direction, remains opt-in and is never fed
into the current aquifer-alert percentile proxy.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from aguayluz.usgs_water_api import (  # noqa: E402
    OGC_COLLECTIONS,
    PR_BBOX,
    bare_site,
    flatten_features,
    iter_ogc_pages,
    merge_by_key,
    read_json_documents,
    read_jsonl,
    reading_row,
    safe_float,
    source_receipt,
    write_jsonl,
)

DEFAULT_CODES = ("72019",)


def year_slices(start: date, end: date) -> list[tuple[date, date]]:
    slices: list[tuple[date, date]] = []
    current = start
    while current < end:
        next_year = min(date(current.year + 1, 1, 1), end)
        slices.append((current, next_year))
        current = next_year
    return slices


def _coords(feature: dict) -> tuple[float | None, float | None]:
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or []
    if geometry.get("type") != "Point" or len(coords) < 2:
        return None, None
    try:
        lon, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        return None, None
    if not (-67.95 <= lon <= -65.20 and 17.70 <= lat <= 18.70):
        return None, None
    return round(lat, 6), round(lon, 6)


def rows_from_documents(documents: list[dict]) -> tuple[list[dict], list[dict], dict[str, int]]:
    rows: list[dict] = []
    assets: dict[str, dict] = {}
    skipped = {"missing_value": 0, "missing_date": 0, "nonstatic_qualifier": 0}
    for feature in flatten_features(documents):
        props = feature.get("properties") or {}
        value = safe_float(props.get("value"))
        site = bare_site(props.get("monitoring_location_id"))
        pcode = str(props.get("parameter_code") or "").strip()
        year, month, day = props.get("year"), props.get("month"), props.get("day")
        observed_at = ""
        try:
            observed_at = date(int(year), int(month), int(day)).isoformat()
        except (TypeError, ValueError):
            observed_at = str(props.get("time") or "")
        if value is None:
            skipped["missing_value"] += 1
            continue
        if not observed_at:
            skipped["missing_date"] += 1
            continue
        qualifier_raw = props.get("qualifier")
        qualifiers = (
            [str(qualifier_raw)]
            if isinstance(qualifier_raw, str)
            else [str(v) for v in (qualifier_raw or [])]
        )
        clean = not qualifiers or all(item.lower() == "static" for item in qualifiers)
        if not clean:
            skipped["nonstatic_qualifier"] += 1
        lat, lon = _coords(feature)
        asset_id = f"USGSFM_{site}"
        if site and asset_id not in assets:
            assets[asset_id] = {
                "asset_id": asset_id,
                "asset_name": str(
                    props.get("monitoring_location_name")
                    or props.get("site_name")
                    or f"USGS field-measurement well {site}"
                ).strip(),
                "asset_type": "water",
                "asset_subtype": "groundwater_field_measurement_well",
                "operator": "USGS",
                "municipality": "unknown",
                "geometry_type": "point" if lat is not None else "unknown",
                "status": "active",
                "source_ref": f"USGS OGC monitoring location supporting field measurements, site {site}",
                "evidence_tier": "T1",
                "confidence": 80 if lat is not None else 65,
                "review_status": "accepted" if lat is not None else "needs_review",
            }
            if lat is not None:
                assets[asset_id]["lat"] = lat
                assets[asset_id]["lon"] = lon
        row = reading_row(
            site=site,
            parameter_code=pcode,
            value=value,
            unit=str(props.get("unit_of_measure") or "ft"),
            observed_at=observed_at,
            source_ref=f"USGS OGC field-measurements, site {site}, parameter {pcode}",
            provisional=False,
            id_namespace="usgsfm",
            asset_prefix="USGSFM_",
            review_status="accepted" if clean else "needs_review",
        )
        if row:
            rows.append(row)
    return rows, [assets[key] for key in sorted(assets)], skipped


def fetch_live(days: int, parameter_codes: list[str], page_size: int) -> list[dict]:
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=days)
    url = f"{OGC_COLLECTIONS}/field-measurements/items"
    documents: list[dict] = []
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        for pcode in parameter_codes:
            for left, right in year_slices(start, end):
                params = {
                    "bbox": ",".join(str(v) for v in PR_BBOX),
                    "parameter_code": pcode,
                    "datetime": f"{left.isoformat()}T00:00:00Z/{right.isoformat()}T00:00:00Z",
                    "limit": page_size,
                }
                documents.extend(iter_ogc_pages(client, url, params, page_size=page_size))
    return documents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", nargs="*", type=Path)
    parser.add_argument("--days", type=int, default=3650)
    parser.add_argument("--parameter-codes", nargs="+", default=list(DEFAULT_CODES))
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument(
        "--out", type=Path, default=Path("data/usgs_field_measurements_readings.jsonl")
    )
    parser.add_argument(
        "--assets-out", type=Path, default=Path("data/utility_assets.jsonl")
    )
    parser.add_argument(
        "--receipt", type=Path, default=Path("data/usgs_field_measurements_receipt.json")
    )
    args = parser.parse_args()
    live = not bool(args.src)
    try:
        docs = (
            read_json_documents(args.src)
            if args.src
            else fetch_live(max(1, args.days), args.parameter_codes, args.page_size)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"USGS field-measurements fetch failed: {exc}", file=sys.stderr)
        return 1
    rows, assets, skipped = rows_from_documents(docs)
    combined = merge_by_key(read_jsonl(args.out), rows, "reading_id")
    existing_assets = [
        row
        for row in read_jsonl(args.assets_out)
        if not str(row.get("asset_id") or "").startswith("USGSFM_")
    ]
    write_jsonl(args.assets_out, [*existing_assets, *assets])
    write_jsonl(args.out, combined)
    receipt = source_receipt(
        category="ogc_field_measurements",
        source_url=f"{OGC_COLLECTIONS}/field-measurements/items",
        rows_written=len(rows) + len(assets),
        skipped=skipped,
        live=live,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(assets)} field-measurement assets and {len(rows)} readings ({len(combined)} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
