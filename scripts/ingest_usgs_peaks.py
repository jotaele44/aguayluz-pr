#!/usr/bin/env python3
"""Ingest USGS OGC annual peak discharge and peak-stage observations."""
from __future__ import annotations

import argparse
import json
import sys
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
    stable_hash,
    write_jsonl,
)


def rows_from_documents(documents: list[dict]) -> tuple[list[dict], dict[str, int]]:
    rows: list[dict] = []
    skipped = {"missing_discharge": 0, "missing_date": 0}
    for feature in flatten_features(documents):
        props = feature.get("properties") or {}
        site = bare_site(props.get("monitoring_location_id"))
        observed_at = str(
            props.get("peak_date")
            or props.get("peak_time")
            or props.get("time")
            or ""
        )
        qualifiers = props.get("peak_discharge_qualifiers") or props.get("qualifier") or []
        qualifier_token = stable_hash(*([qualifiers] if isinstance(qualifiers, str) else qualifiers))[:8]
        discharge = safe_float(
            props.get("peak_discharge")
            or props.get("discharge")
            or props.get("value")
        )
        stage = safe_float(
            props.get("peak_gage_height")
            or props.get("gage_height")
            or props.get("peak_stage")
        )
        if not observed_at:
            skipped["missing_date"] += 1
            continue
        if discharge is None:
            skipped["missing_discharge"] += 1
        else:
            row = reading_row(
                site=site,
                parameter_code="00060",
                value=discharge,
                unit=str(props.get("discharge_unit") or "ft3/s"),
                observed_at=observed_at,
                source_ref=f"USGS OGC peaks, site {site}, qualifier {qualifier_token}",
                provisional=False,
                id_namespace=f"usgspeakq{qualifier_token}",
            )
            if row:
                rows.append(row)
        if stage is not None:
            row = reading_row(
                site=site,
                parameter_code="00065",
                value=stage,
                unit=str(props.get("gage_height_unit") or "ft"),
                observed_at=observed_at,
                source_ref=f"USGS OGC peaks stage, site {site}, qualifier {qualifier_token}",
                provisional=False,
                id_namespace=f"usgspeakh{qualifier_token}",
            )
            if row:
                rows.append(row)
    return rows, skipped


def fetch_live(page_size: int) -> list[dict]:
    url = f"{OGC_COLLECTIONS}/peaks/items"
    params = {"bbox": ",".join(str(v) for v in PR_BBOX), "limit": page_size}
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        return list(iter_ogc_pages(client, url, params, page_size=page_size))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", nargs="*", type=Path)
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--out", type=Path, default=Path("data/usgs_peaks_readings.jsonl"))
    parser.add_argument("--receipt", type=Path, default=Path("data/usgs_peaks_receipt.json"))
    args = parser.parse_args()
    live = not bool(args.src)
    try:
        docs = read_json_documents(args.src) if args.src else fetch_live(args.page_size)
    except Exception as exc:  # noqa: BLE001
        print(f"USGS peaks fetch failed: {exc}", file=sys.stderr)
        return 1
    rows, skipped = rows_from_documents(docs)
    combined = merge_by_key(read_jsonl(args.out), rows, "reading_id")
    write_jsonl(args.out, combined)
    receipt = source_receipt(
        category="ogc_annual_peaks",
        source_url=f"{OGC_COLLECTIONS}/peaks/items",
        rows_written=len(rows),
        skipped=skipped,
        live=live,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(rows)} peak readings ({len(combined)} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
