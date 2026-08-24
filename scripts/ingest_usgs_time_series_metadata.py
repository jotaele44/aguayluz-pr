#!/usr/bin/env python3
"""Build Puerto Rico USGS monitoring-location and time-series metadata registries."""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import date
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
    read_json_documents,
    source_receipt,
    stable_hash,
    write_jsonl,
)


def location_rows(documents: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for feature in flatten_features(documents):
        props = feature.get("properties") or {}
        site = bare_site(
            props.get("monitoring_location_id")
            or props.get("id")
            or props.get("monitoring_location_number")
        )
        if not site:
            continue
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") if geometry.get("type") == "Point" else None
        row = {
            "location_id": f"USGS-{site}",
            "site_no": site,
            "name": props.get("monitoring_location_name") or props.get("name"),
            "agency_code": props.get("agency_code") or "USGS",
            "site_type_code": props.get("site_type_code"),
            "hydrologic_unit_code": props.get("hydrologic_unit_code"),
            "state_code": props.get("state_code"),
            "county_code": props.get("county_code"),
            "altitude": props.get("altitude"),
            "vertical_datum": props.get("vertical_datum"),
            "aquifer_code": props.get("aquifer_code"),
            "well_constructed_depth": props.get("well_constructed_depth"),
            "source_ref": f"{OGC_COLLECTIONS}/monitoring-locations/items",
            "evidence_tier": "T1",
        }
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            row["lon"], row["lat"] = coordinates[0], coordinates[1]
        rows.append(row)
    return sorted(rows, key=lambda row: row["location_id"])


def metadata_rows(documents: list[dict], stale_days: int) -> list[dict]:
    today = date.today()
    rows: list[dict] = []
    for feature in flatten_features(documents):
        props = feature.get("properties") or {}
        series_id = str(feature.get("id") or props.get("id") or "").strip()
        site = bare_site(props.get("monitoring_location_id"))
        if not series_id or not site:
            continue
        end_raw = str(props.get("end") or props.get("end_utc") or "")
        end_day = end_raw[:10] if len(end_raw) >= 10 else None
        age_days = None
        if end_day:
            with contextlib.suppress(ValueError):
                age_days = (today - date.fromisoformat(end_day)).days
        gap_interval = props.get("data_gap_interval")
        status = "unknown"
        if age_days is not None:
            status = "fresh" if age_days <= stale_days else "stale"
        if gap_interval:
            status = "publication_gap"
        thresholds = props.get("thresholds")
        row = {
            "time_series_id": series_id,
            "monitoring_location_id": f"USGS-{site}",
            "parameter_code": props.get("parameter_code"),
            "parameter_name": props.get("parameter_name"),
            "parameter_description": props.get("parameter_description"),
            "unit_of_measure": props.get("unit_of_measure"),
            "statistic_id": props.get("statistic_id"),
            "begin": props.get("begin") or props.get("begin_utc"),
            "end": props.get("end") or props.get("end_utc"),
            "last_modified": props.get("last_modified"),
            "operational_thresholds": thresholds if isinstance(thresholds, list) else [],
            "data_gap_interval": gap_interval,
            "freshness_status": status,
            "age_days": age_days,
            "source_hash": stable_hash(series_id, props.get("last_modified"), end_raw, thresholds),
            "source_ref": f"{OGC_COLLECTIONS}/time-series-metadata/items",
            "evidence_tier": "T1",
        }
        rows.append(row)
    return sorted(rows, key=lambda row: row["time_series_id"])


def fetch_collection(collection: str, page_size: int) -> list[dict]:
    url = f"{OGC_COLLECTIONS}/{collection}/items"
    params = {"bbox": ",".join(str(v) for v in PR_BBOX), "limit": page_size}
    documents: list[dict] = []
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        documents.extend(iter_ogc_pages(client, url, params, page_size=page_size))
    return documents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src-locations", nargs="*", type=Path)
    parser.add_argument("--src-series", nargs="*", type=Path)
    parser.add_argument("--locations-out", type=Path, default=Path("data/usgs_monitoring_locations.jsonl"))
    parser.add_argument("--series-out", type=Path, default=Path("data/usgs_time_series_metadata.jsonl"))
    parser.add_argument("--receipt", type=Path, default=Path("data/usgs_metadata_receipt.json"))
    parser.add_argument("--stale-days", type=int, default=7)
    parser.add_argument("--page-size", type=int, default=500)
    args = parser.parse_args()

    live = not (args.src_locations or args.src_series)
    try:
        location_docs = (
            read_json_documents(args.src_locations)
            if args.src_locations
            else fetch_collection("monitoring-locations", args.page_size)
        )
        series_docs = (
            read_json_documents(args.src_series)
            if args.src_series
            else fetch_collection("time-series-metadata", args.page_size)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"USGS metadata fetch failed: {exc}", file=sys.stderr)
        return 1

    locations = location_rows(location_docs)
    series = metadata_rows(series_docs, max(0, args.stale_days))
    write_jsonl(args.locations_out, locations)
    write_jsonl(args.series_out, series)
    skipped = {
        "location_features_without_id": len(flatten_features(location_docs)) - len(locations),
        "series_features_without_id": len(flatten_features(series_docs)) - len(series),
        "stale_series": sum(row["freshness_status"] == "stale" for row in series),
        "publication_gap_series": sum(row["freshness_status"] == "publication_gap" for row in series),
    }
    receipt = source_receipt(
        category="monitoring_locations_and_time_series_metadata",
        source_url=OGC_COLLECTIONS,
        rows_written=len(locations) + len(series),
        skipped=skipped,
        live=live,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(locations)} locations and {len(series)} time-series rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
