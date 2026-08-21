"""JSONL source-of-truth persistence for the environmental exposure graph."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import DATA_DIR
from .environmental_exposure import integrity_report, validate_relationship
from .models import validate_against_schema

ENTITIES_PATH = DATA_DIR / "environmental_entities.jsonl"
OBSERVATIONS_PATH = DATA_DIR / "environmental_observations.jsonl"
GEOMETRIES_PATH = DATA_DIR / "environmental_geometries.jsonl"
RELATIONSHIPS_PATH = DATA_DIR / "environmental_relationships.jsonl"
EVENTS_PATH = DATA_DIR / "environmental_exposure_events.jsonl"
UTILITY_ASSETS_PATH = DATA_DIR / "utility_assets.jsonl"

_SPECS = {
    "environmental_entity": (ENTITIES_PATH, "entity_id"),
    "environmental_observation": (OBSERVATIONS_PATH, "observation_id"),
    "environmental_geometry": (GEOMETRIES_PATH, "geometry_id"),
    "exposure_relationship": (RELATIONSHIPS_PATH, "relationship_id"),
    "environmental_exposure_event": (EVENTS_PATH, "event_id"),
}


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def load(kind: str, path: Path | None = None) -> list[dict[str, Any]]:
    default_path, _ = _SPECS[kind]
    rows = _read(path or default_path)
    for row in rows:
        validate_against_schema(kind, row)
        if kind == "exposure_relationship":
            validate_relationship(row)
    return rows


def merge(kind: str, existing: list[dict], incoming: list[dict]) -> list[dict]:
    _, key = _SPECS[kind]
    by_id = {row[key]: row for row in existing}
    for row in incoming:
        validate_against_schema(kind, row)
        if kind == "exposure_relationship":
            validate_relationship(row)
        by_id[row[key]] = row
    return sorted(by_id.values(), key=lambda row: str(row[key]))


def write(kind: str, rows: list[dict], path: Path | None = None) -> None:
    default_path, _ = _SPECS[kind]
    target = path or default_path
    _write(target, merge(kind, load(kind, target), rows))


def graph_integrity(
    entities_path: Path = ENTITIES_PATH,
    observations_path: Path = OBSERVATIONS_PATH,
    geometries_path: Path = GEOMETRIES_PATH,
    relationships_path: Path = RELATIONSHIPS_PATH,
    utility_assets_path: Path = UTILITY_ASSETS_PATH,
) -> dict[str, Any]:
    entities = load("environmental_entity", entities_path)
    observations = load("environmental_observation", observations_path)
    geometries = load("environmental_geometry", geometries_path)
    relationships = load("exposure_relationship", relationships_path)
    utility_assets = _read(utility_assets_path)
    return integrity_report(
        entity_ids=(row["entity_id"] for row in entities),
        observation_ids=(row["observation_id"] for row in observations),
        geometry_ids=(row["geometry_id"] for row in geometries),
        relationships=relationships,
        external_entity_ids=(
            str(row["asset_id"]) for row in utility_assets if row.get("asset_id")
        ),
    )
