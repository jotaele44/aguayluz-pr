#!/usr/bin/env python3
"""Export NWPS gauge state into evidence-gated PR Grid V2 source records.

This exporter never assigns Cell_IDs. It only transforms the frozen AguaYLuz
NWPS state snapshot into:
1. exact source-coordinate rows for Spiderweb's authority-side V2 binder; and
2. minimal producer record metadata for AguaYLuz Cell_Profile materialization.

Coordinates are admitted only when the source-derived NWPS state row preserves:
- stable record_id
- numeric latitude/longitude
- bulk_manifestation_id
- retrieved_at

Any missing or duplicate identity/provenance fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

REPOSITORY = "aguayluz-pr"
SOURCE_CRS = "EPSG:4326"
COORDINATE_EVIDENCE_STATE = "VERIFIED_SOURCE_COORDINATE"
CATEGORY = "NWPS_GAUGE"
CONTRACT = "aguayluz-nwps-grid-v2-source-export/1.0"


class ExportError(ValueError):
    """Raised when source state cannot support exact V2 binding."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_jsonl(rows: list[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        for row in rows
    ).encode("utf-8")


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExportError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ExportError(f"{name} must be finite")
    return number


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExportError(f"{name} must be a non-empty string")
    return value.strip()


def load_state(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExportError(f"{path}:{lineno}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ExportError(f"{path}:{lineno}: expected JSON object")
        rows.append(value)
    if not rows:
        raise ExportError("NWPS state snapshot is empty")
    return rows


def export_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    manifestations: set[str] = set()

    for row in rows:
        record_id = _text("record_id", row.get("record_id"))
        if record_id in seen:
            raise ExportError(f"duplicate record_id: {record_id}")
        seen.add(record_id)

        lon = _finite_number("longitude", row.get("longitude"))
        lat = _finite_number("latitude", row.get("latitude"))
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ExportError(f"coordinate outside EPSG:4326 bounds: {record_id}")

        manifestation = _text("bulk_manifestation_id", row.get("bulk_manifestation_id"))
        retrieved_at = _text("retrieved_at", row.get("retrieved_at"))
        lid = _text("lid", row.get("lid"))
        manifestations.add(manifestation)

        bindings.append(
            {
                "Repository": REPOSITORY,
                "Record_ID": record_id,
                "Source_X": lon,
                "Source_Y": lat,
                "Source_CRS": SOURCE_CRS,
                "Coordinate_Evidence_State": COORDINATE_EVIDENCE_STATE,
                "Spatial_Role": "POINT_LOCATION",
                "Uncertainty_Class": "EXACT",
                "Source_System": "NWPS API v1",
                "Source_LID": lid,
                "Source_Manifestation_ID": manifestation,
                "Source_Retrieved_At": retrieved_at,
            }
        )
        records.append(
            {
                "Repository": REPOSITORY,
                "Record_ID": record_id,
                "Category": CATEGORY,
                "Source_System": "NWPS API v1",
                "Source_LID": lid,
                "Source_Manifestation_ID": manifestation,
                "Source_Retrieved_At": retrieved_at,
                "Name": row.get("name"),
                "USGS_ID": row.get("usgs_id"),
                "Asset_ID": row.get("asset_id"),
            }
        )

    bindings.sort(key=lambda r: r["Record_ID"])
    records.sort(key=lambda r: r["Record_ID"])
    receipt = {
        "Contract": CONTRACT,
        "Repository": REPOSITORY,
        "Source_CRS": SOURCE_CRS,
        "Coordinate_Evidence_State": COORDINATE_EVIDENCE_STATE,
        "Input_Record_Count": len(rows),
        "Binding_Input_Record_Count": len(bindings),
        "Profile_Record_Count": len(records),
        "Unique_Record_ID_Count": len(seen),
        "Source_Manifestation_Count": len(manifestations),
        "Source_Manifestation_IDs": sorted(manifestations),
        "State": "PASS",
    }
    return bindings, records, receipt


def write_outputs(
    *,
    source: Path,
    binding_out: Path,
    records_out: Path,
    receipt_out: Path,
) -> dict[str, Any]:
    source_bytes = source.read_bytes()
    bindings, records, receipt = export_rows(load_state(source))
    binding_bytes = canonical_jsonl(bindings)
    records_bytes = canonical_jsonl(records)

    binding_out.parent.mkdir(parents=True, exist_ok=True)
    records_out.parent.mkdir(parents=True, exist_ok=True)
    receipt_out.parent.mkdir(parents=True, exist_ok=True)
    binding_out.write_bytes(binding_bytes)
    records_out.write_bytes(records_bytes)

    receipt.update(
        {
            "Source_Path": str(source),
            "Source_SHA256": sha256_bytes(source_bytes),
            "Source_Bytes": len(source_bytes),
            "Binding_Input_SHA256": sha256_bytes(binding_bytes),
            "Binding_Input_Bytes": len(binding_bytes),
            "Profile_Records_SHA256": sha256_bytes(records_bytes),
            "Profile_Records_Bytes": len(records_bytes),
        }
    )
    receipt_out.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/nwps_gauge_state.jsonl"))
    parser.add_argument("--binding-out", type=Path, required=True)
    parser.add_argument("--records-out", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    args = parser.parse_args()

    receipt = write_outputs(
        source=args.source,
        binding_out=args.binding_out,
        records_out=args.records_out,
        receipt_out=args.receipt_out,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
