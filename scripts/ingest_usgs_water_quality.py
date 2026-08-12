#!/usr/bin/env python3
"""Discover and ingest Puerto Rico water-quality observations from WQP and Samples API.

Statewide live acquisition is sliced by calendar year and capped per slice. Numeric
results become monitoring readings. Non-detects are preserved in a separate censored
ledger and are never converted to zero.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from aguayluz.usgs_water_api import (  # noqa: E402
    PR_STATE_FIPS,
    SAMPLES_RESULTS,
    WQP_RESULTS,
    WQP_STATIONS,
    api_headers,
    bare_site,
    merge_by_key,
    read_jsonl,
    safe_float,
    source_receipt,
    stable_hash,
    write_jsonl,
)


def _first(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def parse_csv(text: str, max_rows: int) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for index, row in enumerate(reader):
        if index >= max_rows:
            break
        rows.append(dict(row))
    return rows


def station_rows(source_rows: list[dict[str, str]]) -> list[dict]:
    dedup: dict[str, dict] = {}
    for row in source_rows:
        identifier = _first(
            row,
            "MonitoringLocationIdentifier",
            "Location_Identifier",
            "MonitoringLocation_Identifier",
        )
        if not identifier:
            continue
        dedup[identifier] = {
            "monitoring_location_id": identifier,
            "name": _first(row, "MonitoringLocationName", "Location_Name"),
            "organization_id": _first(row, "OrganizationIdentifier", "Organization_Identifier"),
            "type": _first(row, "MonitoringLocationTypeName", "Location_Type"),
            "state_code": _first(row, "StateCode", "State_Code"),
            "county_code": _first(row, "CountyCode", "County_Code"),
            "latitude": safe_float(_first(row, "LatitudeMeasure", "Location_Latitude")),
            "longitude": safe_float(_first(row, "LongitudeMeasure", "Location_Longitude")),
            "source_ref": "Water Quality Portal statewide station discovery",
            "evidence_tier": "T1",
        }
    return [dedup[key] for key in sorted(dedup)]


def asset_id_for(location_id: str) -> str:
    site = bare_site(location_id)
    if location_id.upper().startswith("USGS-") and site:
        return f"USGSWQ_{site}"
    return f"WQP_{stable_hash(location_id)[:20]}"


def asset_rows(source_rows: list[dict[str, str]]) -> list[dict]:
    assets: dict[str, dict] = {}
    for row in source_rows:
        location_id = _first(
            row,
            "MonitoringLocationIdentifier",
            "Location_Identifier",
            "MonitoringLocation_Identifier",
        )
        if not location_id:
            continue
        asset_id = asset_id_for(location_id)
        lat = safe_float(_first(row, "LatitudeMeasure", "Location_Latitude"))
        lon = safe_float(_first(row, "LongitudeMeasure", "Location_Longitude"))
        if lat is not None and not 17.70 <= lat <= 18.70:
            lat = None
        if lon is not None and not -67.95 <= lon <= -65.20:
            lon = None
        has_coords = lat is not None and lon is not None
        name = _first(row, "MonitoringLocationName", "Location_Name") or location_id
        provider = _first(row, "OrganizationIdentifier", "Organization_Identifier") or None
        asset = {
            "asset_id": asset_id,
            "asset_name": name,
            "asset_type": "water",
            "asset_subtype": "water_quality_monitoring_location",
            "operator": provider,
            "municipality": "unknown",
            "geometry_type": "point" if has_coords else "unknown",
            "status": "active",
            "source_ref": f"Water Quality Portal monitoring location {location_id}",
            "source_hash": stable_hash(location_id, name, lat, lon),
            "evidence_tier": "T1",
            "confidence": 80 if has_coords else 65,
            "review_status": "accepted" if has_coords else "needs_review",
        }
        if has_coords:
            asset["lat"], asset["lon"] = lat, lon
        assets[asset_id] = asset
    return [assets[key] for key in sorted(assets)]


def result_rows(
    source_rows: list[dict[str, str]],
) -> tuple[list[dict], list[dict], dict[str, int]]:
    readings: list[dict] = []
    censored: list[dict] = []
    skipped = {"missing_site": 0, "missing_date": 0, "missing_unit": 0, "nondetect": 0}
    seen: set[str] = set()
    for row in source_rows:
        location_id = _first(
            row,
            "MonitoringLocationIdentifier",
            "Location_Identifier",
            "MonitoringLocation_Identifier",
        )
        site = bare_site(location_id)
        observed = _first(row, "ActivityStartDate", "Activity_StartDate")[:10]
        characteristic = _first(row, "CharacteristicName", "Result_Characteristic") or "result"
        unit = _first(row, "ResultMeasure/MeasureUnitCode", "Result_MeasureUnit")
        raw = _first(row, "ResultMeasureValue", "Result_Measure")
        detection = _first(
            row,
            "ResultDetectionConditionText",
            "Result_DetectionCondition",
            "DetectionCondition",
        )
        activity_id = _first(row, "ActivityIdentifier", "Activity_Identifier")
        result_id = _first(row, "ResultIdentifier", "Result_Identifier")
        provider = _first(row, "OrganizationIdentifier", "Organization_Identifier") or "unknown"
        identity = stable_hash(provider, location_id, activity_id, result_id, characteristic, observed)
        if identity in seen:
            continue
        seen.add(identity)
        if not site:
            skipped["missing_site"] += 1
            continue
        if len(observed) != 10:
            skipped["missing_date"] += 1
            continue
        value = safe_float(raw)
        if detection or value is None:
            skipped["nondetect"] += 1
            censored.append(
                {
                    "censored_id": f"AYL_WQ_CENS_{identity[:24]}",
                    "monitoring_location_id": location_id,
                    "observed_date": observed,
                    "characteristic": characteristic,
                    "detection_condition": detection or "value_not_numeric",
                    "reported_value": raw or None,
                    "reported_unit": unit or None,
                    "source_provider": provider,
                    "source_ref": "WQP/USGS Samples result; preserved as censored, not zero",
                    "evidence_tier": "T1",
                }
            )
            continue
        if not unit:
            skipped["missing_unit"] += 1
            continue
        pcode = _first(row, "USGSpcode", "USGSParameterCode") or characteristic[:32]
        readings.append(
            {
                "reading_id": f"AYL_RDG_{observed.replace('-', '')}_usgswq_{identity[:20]}",
                "asset_id": asset_id_for(location_id),
                "site_no": site,
                "metric": "water_quality",
                "parameter_code": pcode,
                "value": value,
                "unit": unit,
                "observed_date": observed,
                "provisional": False,
                "source_ref": f"WQP/USGS Samples, {provider}, {characteristic}",
                "source_hash": identity,
                "evidence_tier": "T1",
                "confidence": 80,
                "review_status": "accepted",
            }
        )
    return readings, censored, skipped


def fetch_text(url: str, params: list[tuple[str, str]] | dict[str, str]) -> str:
    with httpx.Client(timeout=300, follow_redirects=True) as client:
        response = client.get(url, params=params, headers=api_headers())
        response.raise_for_status()
        return response.text


def fetch_statewide(year: int, max_rows: int) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    station_text = fetch_text(
        WQP_STATIONS,
        {"statecode": f"US:{PR_STATE_FIPS}", "mimeType": "csv", "zip": "no"},
    )
    result_text = fetch_text(
        WQP_RESULTS,
        {
            "statecode": f"US:{PR_STATE_FIPS}",
            "startDateLo": f"01-01-{year}",
            "startDateHi": f"12-31-{year}",
            "mimeType": "csv",
            "zip": "no",
        },
    )
    return parse_csv(station_text, max_rows), parse_csv(result_text, max_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src-stations", type=Path)
    parser.add_argument("--src-results", nargs="*", type=Path)
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--max-rows", type=int, default=100_000)
    parser.add_argument(
        "--stations-out", type=Path, default=Path("data/usgs_water_quality_locations.jsonl")
    )
    parser.add_argument(
        "--assets-out", type=Path, default=Path("data/utility_assets.jsonl")
    )
    parser.add_argument(
        "--readings-out", type=Path, default=Path("data/usgs_water_quality_readings.jsonl")
    )
    parser.add_argument(
        "--censored-out", type=Path, default=Path("data/usgs_water_quality_censored.jsonl")
    )
    parser.add_argument(
        "--receipt", type=Path, default=Path("data/usgs_water_quality_receipt.json")
    )
    args = parser.parse_args()
    live = not bool(args.src_results)
    try:
        if args.src_results:
            station_source = (
                parse_csv(args.src_stations.read_text(encoding="utf-8"), args.max_rows)
                if args.src_stations
                else []
            )
            result_source: list[dict[str, str]] = []
            for path in args.src_results:
                result_source.extend(parse_csv(path.read_text(encoding="utf-8"), args.max_rows))
        else:
            station_source, result_source = fetch_statewide(args.year, args.max_rows)
    except Exception as exc:  # noqa: BLE001
        print(f"water-quality discovery failed: {exc}", file=sys.stderr)
        return 1

    stations = station_rows(station_source)
    assets = asset_rows([*station_source, *result_source])
    readings, censored, skipped = result_rows(result_source)
    write_jsonl(args.stations_out, stations)
    owned_ids = {row["asset_id"] for row in assets}
    existing_assets = [
        row for row in read_jsonl(args.assets_out) if row.get("asset_id") not in owned_ids
    ]
    write_jsonl(args.assets_out, [*existing_assets, *assets])
    write_jsonl(
        args.readings_out,
        merge_by_key(read_jsonl(args.readings_out), readings, "reading_id"),
    )
    write_jsonl(
        args.censored_out,
        merge_by_key(read_jsonl(args.censored_out), censored, "censored_id"),
    )
    receipt = source_receipt(
        category="water_quality_portal_and_samples",
        source_url=f"{WQP_STATIONS}; {WQP_RESULTS}; {SAMPLES_RESULTS}",
        rows_written=len(stations) + len(assets) + len(readings) + len(censored),
        skipped=skipped,
        live=live,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(
        f"wrote {len(stations)} stations, {len(assets)} assets, {len(readings)} numeric readings, "
        f"{len(censored)} censored results"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
