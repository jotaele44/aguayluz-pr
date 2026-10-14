#!/usr/bin/env python3
"""Export source-native USGS monitoring points as PR Grid V2 binding candidates.

This producer does not transform coordinates and does not assign Cell_IDs.
Spiderweb remains the sole geometry/binding authority. Only source-native T1
monitoring-location points are eligible for this exact-source-coordinate slice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPOSITORY = "aguayluz-pr"
SOURCE_CRS = "EPSG:4326"
COORDINATE_EVIDENCE_STATE = "VERIFIED_SOURCE_COORDINATE"
UNCERTAINTY_CLASS = "EXACT"
SPATIAL_ROLE = "MONITORING_LOCATION"
CANDIDATE_STATE = "SOURCE_COORDINATE_ELIGIBLE_NOT_BOUND"
CONTRACT = "pr-grid-v2-source-coordinate-candidate/1.0"
RECEIPT_CONTRACT = "pr-grid-v2-source-coordinate-candidate-receipt/1.0"

DEFAULT_INPUT = Path("data/usgs_monitoring_locations.jsonl")
DEFAULT_OUTPUT = Path("data/federation/pr_grid_v2_source_coordinate_candidates.jsonl")
DEFAULT_RECEIPT = Path(
    "data/federation/pr_grid_v2_source_coordinate_candidates.receipt.json"
)

PR_LAT_MIN, PR_LAT_MAX = 17.70, 18.70
PR_LON_MIN, PR_LON_MAX = -67.95, -65.20


class CandidateExportError(ValueError):
    """Source-coordinate candidate export cannot be certified."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise CandidateExportError(f"{path}:{lineno}: expected JSON object")
            rows.append(value)
    return rows


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def build_candidates(
    source_rows: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates: list[dict[str, Any]] = []
    skipped = {
        "missing_identity": 0,
        "missing_coordinates": 0,
        "out_of_pr_bounds": 0,
        "non_t1_source": 0,
        "missing_source_ref": 0,
    }
    seen: dict[str, tuple[float, float]] = {}

    for row in source_rows:
        location_id = str(row.get("location_id") or "").strip()
        if not location_id:
            skipped["missing_identity"] += 1
            continue

        lon = _number(row.get("lon"))
        lat = _number(row.get("lat"))
        if lon is None or lat is None:
            skipped["missing_coordinates"] += 1
            continue
        if not (PR_LON_MIN <= lon <= PR_LON_MAX and PR_LAT_MIN <= lat <= PR_LAT_MAX):
            skipped["out_of_pr_bounds"] += 1
            continue

        if row.get("evidence_tier") != "T1":
            skipped["non_t1_source"] += 1
            continue
        source_ref = str(row.get("source_ref") or "").strip()
        if not source_ref:
            skipped["missing_source_ref"] += 1
            continue

        prior = seen.get(location_id)
        current = (lon, lat)
        if prior is not None:
            if prior != current:
                raise CandidateExportError(
                    f"conflicting coordinates for monitoring location {location_id}"
                )
            raise CandidateExportError(
                f"duplicate monitoring location identity: {location_id}"
            )
        seen[location_id] = current

        candidates.append(
            {
                "Contract": CONTRACT,
                "Repository": REPOSITORY,
                "Record_ID": location_id,
                "Source_X": lon,
                "Source_Y": lat,
                "Source_CRS": SOURCE_CRS,
                "Coordinate_Evidence_State": COORDINATE_EVIDENCE_STATE,
                "Uncertainty_Class": UNCERTAINTY_CLASS,
                "Spatial_Role": SPATIAL_ROLE,
                "Source_Ref": source_ref,
                "Evidence_Tier": "T1",
                "Candidate_State": CANDIDATE_STATE,
                "Geometry_Authority": "spiderweb-pr",
                "Cell_ID": None,
            }
        )

    candidates.sort(key=lambda row: row["Record_ID"])
    return candidates, skipped


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
        for row in rows
    ).encode("utf-8")


def export_candidates(
    source_path: Path,
    output_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    if not source_path.is_file():
        raise CandidateExportError(
            f"source monitoring-location ledger unavailable: {source_path}"
        )

    source_payload = source_path.read_bytes()
    source_rows = _read_jsonl(source_path)
    candidates, skipped = build_candidates(source_rows)
    output_payload = _jsonl_bytes(candidates)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output_payload)

    receipt = {
        "contract": RECEIPT_CONTRACT,
        "Producer": REPOSITORY,
        "Source_Artifact": str(source_path),
        "Source_SHA256": _sha256_bytes(source_payload),
        "Source_Bytes": len(source_payload),
        "Source_Row_Count": len(source_rows),
        "Candidate_Output": str(output_path),
        "Candidate_Output_SHA256": _sha256_bytes(output_payload),
        "Candidate_Output_Bytes": len(output_payload),
        "Eligible_Candidate_Count": len(candidates),
        "Skipped_Counts": dict(sorted(skipped.items())),
        "Source_CRS": SOURCE_CRS,
        "Coordinate_Evidence_State": COORDINATE_EVIDENCE_STATE,
        "Uncertainty_Class": UNCERTAINTY_CLASS,
        "Candidate_State": CANDIDATE_STATE,
        "Geometry_Authority": "spiderweb-pr",
        "Cell_ID_Materialized": False,
        "State": "PASS",
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()

    try:
        receipt = export_candidates(args.input, args.output, args.receipt)
    except (CandidateExportError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"FAIL_CLOSED: {exc}\n")

    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
