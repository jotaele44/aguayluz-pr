#!/usr/bin/env python3
"""Ingest USGS Water Data Statistics baselines for registered Puerto Rico sites.

The beta service exposes ``observationNormals`` and ``observationIntervals``.
Outputs remain internal baselines until independently compared with AguaLuz local
percentiles; this script does not replace or silently recalibrate alert thresholds.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from aguayluz.usgs_water_api import (  # noqa: E402
    STATISTICS_ROOT,
    api_headers,
    read_jsonl,
    source_receipt,
    stable_hash,
    write_jsonl,
)


def site_ids_from_assets(path: Path, limit: int) -> list[str]:
    sites: list[str] = []
    for row in read_jsonl(path):
        asset_id = str(row.get("asset_id") or "")
        if asset_id.startswith("USGS_"):
            sites.append(f"USGS-{asset_id.removeprefix('USGS_')}")
    return sorted(set(sites))[:limit]


def _records(document: Any) -> list[dict]:
    if isinstance(document, list):
        return [row for row in document if isinstance(row, dict)]
    if isinstance(document, dict):
        for key in ("items", "data", "features", "observations"):
            value = document.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def normalize(document: Any, endpoint: str) -> list[dict]:
    rows: list[dict] = []
    for raw in _records(document):
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else raw
        values = props.get("values")
        if isinstance(values, list):
            payloads = [value for value in values if isinstance(value, dict)]
        else:
            payloads = [props]
        for value in payloads:
            site = str(
                value.get("monitoring_location_id")
                or props.get("monitoring_location_id")
                or ""
            )
            pcode = str(value.get("parameter_code") or props.get("parameter_code") or "")
            computation = str(
                value.get("computation_type") or props.get("computation_type") or ""
            )
            start = value.get("start_date") or props.get("start_date")
            end = value.get("end_date") or props.get("end_date")
            interval = value.get("interval_type") or props.get("interval_type")
            normal = value.get("normal_type") or props.get("normal_type")
            observed = value.get("value")
            identity = stable_hash(endpoint, site, pcode, computation, start, end, interval, normal)
            rows.append(
                {
                    "baseline_id": f"USGS_STAT_{identity[:24]}",
                    "endpoint": endpoint,
                    "monitoring_location_id": site,
                    "parameter_code": pcode,
                    "computation_type": computation,
                    "interval_type": interval,
                    "normal_type": normal,
                    "start_date": start,
                    "end_date": end,
                    "value": observed,
                    "unit": value.get("unit_of_measure") or props.get("unit_of_measure"),
                    "approval_status": value.get("approval_status") or props.get("approval_status"),
                    "source_ref": f"{STATISTICS_ROOT}/{endpoint}",
                    "evidence_tier": "T1",
                    "local_percentile_replaced": False,
                    "cross_validation_status": "pending",
                }
            )
    return rows


def fetch_endpoint(endpoint: str, sites: list[str], page_size: int) -> Any:
    params: list[tuple[str, str]] = [("page_size", str(page_size))]
    params.extend(("monitoring_location_id", site) for site in sites)
    params.extend(("parameter_code", code) for code in ("00060", "00065", "72019"))
    with httpx.Client(timeout=300, follow_redirects=True) as client:
        response = client.get(
            f"{STATISTICS_ROOT}/{endpoint}",
            params=params,
            headers=api_headers(),
        )
        response.raise_for_status()
        return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src-normals", type=Path)
    parser.add_argument("--src-intervals", type=Path)
    parser.add_argument("--assets", type=Path, default=Path("data/utility_assets.jsonl"))
    parser.add_argument("--site-limit", type=int, default=50)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument(
        "--out", type=Path, default=Path("data/usgs_statistics_baselines.jsonl")
    )
    parser.add_argument(
        "--receipt", type=Path, default=Path("data/usgs_statistics_receipt.json")
    )
    args = parser.parse_args()
    live = not (args.src_normals or args.src_intervals)
    try:
        sites = site_ids_from_assets(args.assets, max(1, args.site_limit))
        normals_doc = (
            json.loads(args.src_normals.read_text(encoding="utf-8"))
            if args.src_normals
            else fetch_endpoint("observationNormals", sites, args.page_size)
        )
        intervals_doc = (
            json.loads(args.src_intervals.read_text(encoding="utf-8"))
            if args.src_intervals
            else fetch_endpoint("observationIntervals", sites, args.page_size)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"statistics fetch failed: {exc}", file=sys.stderr)
        return 1
    rows = normalize(normals_doc, "observationNormals") + normalize(
        intervals_doc, "observationIntervals"
    )
    write_jsonl(args.out, sorted(rows, key=lambda row: row["baseline_id"]))
    receipt = source_receipt(
        category="water_data_statistics",
        source_url=STATISTICS_ROOT,
        rows_written=len(rows),
        skipped={"local_alert_percentiles_replaced": 0},
        live=live,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(rows)} statistics baseline rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
