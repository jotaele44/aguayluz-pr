"""JSONL persistence for the canonical hazard/advisory plane."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import DATA_DIR
from .hazard_plane import HazardRecord, HazardRelationship, Manifestation, integrity_report

RECORDS_PATH = DATA_DIR / "hazard_records.jsonl"
RELATIONSHIPS_PATH = DATA_DIR / "hazard_relationships.jsonl"
MANIFESTATIONS_PATH = DATA_DIR / "hazard_manifestations.jsonl"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"non-object JSONL row in {path}")
        rows.append(row)
    return rows


def load_records() -> list[HazardRecord]:
    return [HazardRecord.model_validate(row) for row in _load_jsonl(RECORDS_PATH)]


def load_relationships() -> list[HazardRelationship]:
    return [HazardRelationship.model_validate(row) for row in _load_jsonl(RELATIONSHIPS_PATH)]


def load_manifestations() -> list[Manifestation]:
    return [Manifestation.model_validate(row) for row in _load_jsonl(MANIFESTATIONS_PATH)]


def graph_integrity() -> dict[str, Any]:
    return integrity_report(load_records(), load_relationships(), load_manifestations())
