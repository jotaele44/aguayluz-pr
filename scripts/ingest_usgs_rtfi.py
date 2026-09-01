#!/usr/bin/env python3
"""Ingest USGS Real-Time Flood Impact reference points for Puerto Rico."""
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
    RTFI_ROOT,
    api_headers,
    source_receipt,
    stable_hash,
    write_jsonl,
)


def _records(document: Any) -> list[dict]:
    if isinstance(document, list):
        return [row for row in document if isinstance(row, dict)]
    if isinstance(document, dict):
        if isinstance(document.get("features"), list):
            return [row for row in document["features"] if isinstance(row, dict)]
        for key in ("items", "data", "referencepoints"):
            if isinstance(document.get(key), list):
                return [row for row in document[key] if isinstance(row, dict)]
    return []


def parse(document: Any) -> tuple[list[dict], list[dict]]:
    locations: list[dict] = []
    edges: list[dict] = []
    for raw in _records(document):
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else raw
        geometry = raw.get("geometry") or {}
        reference_id = str(
            props.get("id")
            or props.get("referencePointId")
            or props.get("reference_point_id")
            or ""
        )
        if not reference_id:
            continue
        nwis = str(
            props.get("nwis_id")
            or props.get("nwisId")
            or props.get("nwis_site")
            or ""
        ).replace("USGS-", "")
        location = {
            "flood_impact_id": f"USGS_RTFI_{reference_id}",
            "reference_point_id": reference_id,
            "name": props.get("name") or props.get("description"),
            "impact_type": props.get("type") or props.get("referencePointType"),
            "elevation": props.get("elevation"),
            "elevation_unit": props.get("elevationUnit") or props.get("elevation_unit"),
            "status": props.get("status") or ("active" if props.get("active", True) else "inactive"),
            "nwis_site_no": nwis or None,
            "nws_id": props.get("nws_id") or props.get("nwsId"),
            "provisional": True,
            "source_ref": f"{RTFI_ROOT}/referencepoints/state/PR",
            "evidence_tier": "T1",
        }
        coordinates = geometry.get("coordinates") if geometry.get("type") == "Point" else None
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            location["lon"], location["lat"] = coordinates[0], coordinates[1]
        locations.append(location)
        if nwis:
            edges.append(
                {
                    "edge_id": f"AYL_EDGE_RTFI_{stable_hash(reference_id, nwis)[:20]}",
                    "from_id": f"USGS_{nwis}",
                    "to_id": f"USGS_RTFI_{reference_id}",
                    "relationship": "MONITORED_BY",
                    "authoritative_association": True,
                    "source_ref": f"{RTFI_ROOT}/referencepoints/{reference_id}",
                    "evidence_tier": "T1",
                    "review_status": "accepted",
                }
            )
    return sorted(locations, key=lambda row: row["flood_impact_id"]), sorted(
        edges, key=lambda row: row["edge_id"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    parser.add_argument(
        "--locations-out", type=Path, default=Path("data/usgs_rtfi_locations.jsonl")
    )
    parser.add_argument(
        "--edges-out", type=Path, default=Path("data/usgs_rtfi_gage_edges.jsonl")
    )
    parser.add_argument("--receipt", type=Path, default=Path("data/usgs_rtfi_receipt.json"))
    args = parser.parse_args()
    live = args.src is None
    try:
        if args.src:
            document = json.loads(args.src.read_text(encoding="utf-8"))
        else:
            with httpx.Client(timeout=180, follow_redirects=True) as client:
                response = client.get(
                    f"{RTFI_ROOT}/referencepoints/state/PR", headers=api_headers()
                )
                response.raise_for_status()
                document = response.json()
    except Exception as exc:  # noqa: BLE001
        print(f"RTFI fetch failed: {exc}", file=sys.stderr)
        return 1
    locations, edges = parse(document)
    write_jsonl(args.locations_out, locations)
    write_jsonl(args.edges_out, edges)
    receipt = source_receipt(
        category="real_time_flood_impacts",
        source_url=f"{RTFI_ROOT}/referencepoints/state/PR",
        rows_written=len(locations) + len(edges),
        skipped={"reference_points_without_authoritative_nwis_edge": len(locations) - len(edges)},
        live=live,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(locations)} RTFI locations and {len(edges)} gage edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
