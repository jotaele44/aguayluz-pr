#!/usr/bin/env python3
"""Ingest modern USGS continuous values for Puerto Rico.

Default mode uses ``latest-continuous`` for one current observation per time series.
``--history-hours`` switches to the bounded ``continuous`` collection.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
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

DEFAULT_PARAMS = ("00060", "00065", "72019", "62615", "00054")


def rows_from_documents(documents: list[dict]) -> tuple[list[dict], dict[str, int]]:
    rows: list[dict] = []
    skipped = {"unsupported_parameter": 0, "missing_value": 0, "missing_identity": 0}
    for feature in flatten_features(documents):
        props = feature.get("properties") or {}
        pcode = str(props.get("parameter_code") or "").strip()
        site = bare_site(props.get("monitoring_location_id"))
        value = safe_float(props.get("value"))
        observed_at = str(props.get("time") or props.get("datetime") or "").strip()
        unit = str(props.get("unit_of_measure") or "").strip()
        approvals = [str(v).lower() for v in (props.get("approvals_status") or [])]
        provisional = "approved" not in approvals if approvals else True
        if value is None:
            skipped["missing_value"] += 1
            continue
        row = reading_row(
            site=site,
            parameter_code=pcode,
            value=value,
            unit=unit,
            observed_at=observed_at,
            source_ref=f"USGS Water Data API continuous, site {site}, parameter {pcode}",
            provisional=provisional,
            id_namespace="usgscv",
        )
        if row is None:
            if not site or not observed_at or not unit:
                skipped["missing_identity"] += 1
            else:
                skipped["unsupported_parameter"] += 1
            continue
        rows.append(row)
    return rows, skipped


def fetch_live(*, history_hours: int, parameter_codes: list[str], page_size: int) -> list[dict]:
    collection = "continuous" if history_hours > 0 else "latest-continuous"
    url = f"{OGC_COLLECTIONS}/{collection}/items"
    params: dict[str, object] = {
        "bbox": ",".join(str(v) for v in PR_BBOX),
        "limit": page_size,
    }
    if history_hours > 0:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=history_hours)
        params["datetime"] = f"{start.isoformat()}/{end.isoformat()}"
    documents: list[dict] = []
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        for pcode in parameter_codes:
            query = dict(params)
            query["parameter_code"] = pcode
            documents.extend(iter_ogc_pages(client, url, query, page_size=page_size))
    return documents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", nargs="*", type=Path)
    parser.add_argument("--out", type=Path, default=Path("data/usgs_continuous_readings.jsonl"))
    parser.add_argument("--receipt", type=Path, default=Path("data/usgs_continuous_receipt.json"))
    parser.add_argument("--history-hours", type=int, default=0)
    parser.add_argument("--parameter-codes", nargs="+", default=list(DEFAULT_PARAMS))
    parser.add_argument("--page-size", type=int, default=500)
    args = parser.parse_args()

    live = not bool(args.src)
    try:
        documents = read_json_documents(args.src) if args.src else fetch_live(
            history_hours=max(0, args.history_hours),
            parameter_codes=args.parameter_codes,
            page_size=args.page_size,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"USGS continuous fetch failed: {exc}", file=sys.stderr)
        return 1

    rows, skipped = rows_from_documents(documents)
    combined = merge_by_key(read_jsonl(args.out), rows, "reading_id")
    write_jsonl(args.out, combined)
    receipt = source_receipt(
        category="continuous_values",
        source_url=f"{OGC_COLLECTIONS}/continuous",
        rows_written=len(rows),
        skipped=skipped,
        live=live,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(rows)} continuous readings ({len(combined)} total) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
