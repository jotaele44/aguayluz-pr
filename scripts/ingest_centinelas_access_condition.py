#!/usr/bin/env python3
"""Validate and ingest a T1 Centinelas access condition into AguaYLuz.

The federation payload is status evidence, never geometry. Exact asset binding is
allowed only through data/reference/el_yunque_access_asset_bindings.json and only
when that registry contains a non-null certified_asset_id.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate

REPO = Path(__file__).resolve().parent.parent
SCHEMA = REPO / "schemas" / "access_condition.v1.schema.json"
BINDINGS = REPO / "data" / "reference" / "el_yunque_access_asset_bindings.json"
OUT_DEFAULT = REPO / "data" / "access_conditions.jsonl"
_FORBIDDEN_GEOMETRY_KEYS = {
    "geometry", "coordinates", "latitude", "longitude", "bbox", "bounding_box",
    "polygon", "polyline", "centroid", "geojson",
}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _binding(asset_key: str | None) -> tuple[str | None, str]:
    if not asset_key:
        return None, "unbound_no_asset_key"
    registry = json.loads(BINDINGS.read_text(encoding="utf-8"))["bindings"]
    entry = registry.get(asset_key)
    if not entry:
        return None, "unbound_unknown_asset_key"
    asset_id = entry.get("certified_asset_id")
    if not asset_id:
        return None, "unbound_no_certified_geometry"
    return str(asset_id), "bound_certified_geometry"


def validate_signal(signal: dict) -> None:
    forbidden = sorted(_FORBIDDEN_GEOMETRY_KEYS.intersection(signal))
    if forbidden:
        raise ValueError(f"access-condition payload must not carry geometry fields: {forbidden}")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validate(instance=signal, schema=schema)
    if signal.get("evidence_tier") != "T1":
        raise ValueError("El Yunque official access condition must preserve T1 evidence")


def promote_access_condition(signal: dict, out: Path = OUT_DEFAULT) -> dict:
    validate_signal(signal)
    bound_asset_id, binding_status = _binding(signal.get("asset_key"))
    row = dict(signal)
    row["bound_asset_id"] = bound_asset_id
    row["binding_status"] = binding_status
    existing = {item["condition_id"]: item for item in _read_jsonl(out)}
    existing[row["condition_id"]] = row
    _write_jsonl(out, list(existing.values()))
    return row
