"""Read-only API for the canonical Puerto Rico hazard/advisory plane."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from aguayluz.hazard_plane import current_records
from aguayluz.hazard_plane_db import (
    graph_integrity,
    load_manifestations,
    load_records,
    load_relationships,
)

router = APIRouter(tags=["hazards"])
ROOT = Path(__file__).resolve().parents[2]
SOURCE_CONFIG = ROOT / "config" / "hazard_advisory_sources.v1.json"


def _source_config() -> dict[str, Any]:
    if not SOURCE_CONFIG.is_file():
        return {"certification_state": "OPEN", "families": [], "unresolved_material": ["SOURCE_CONFIG_MISSING"]}
    try:
        payload = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"certification_state": "OPEN", "families": [], "unresolved_material": ["SOURCE_CONFIG_INVALID"]}
    return payload if isinstance(payload, dict) else {"certification_state": "OPEN", "families": []}


@router.get("/hazards/summary")
def hazard_summary() -> JSONResponse:
    records = load_records()
    relationships = load_relationships()
    manifestations = load_manifestations()
    current = current_records(records)
    source_config = _source_config()
    return JSONResponse({
        "scope": {
            "statement": (
                "Puerto Rico food, agricultural, animal, infectious-disease, wastewater, "
                "water-health and environmental-health records. Spatial/temporal coincidence "
                "is not causation."
            )
        },
        "counts": {
            "records": len(records),
            "current_records": len(current),
            "relationships": len(relationships),
            "manifestations": len(manifestations),
        },
        "family": dict(sorted(Counter(row.family.value for row in current).items())),
        "status": dict(sorted(Counter(row.status.value for row in current).items())),
        "relationship_type": dict(sorted(Counter(row.predicate.value for row in relationships).items())),
        "integrity": graph_integrity(),
        "source_universe": {
            "certification_state": source_config.get("certification_state", "OPEN"),
            "completeness_claimed": bool(source_config.get("completeness_claimed", False)),
            "family_count": len(source_config.get("families") or []),
            "unresolved_material": source_config.get("unresolved_material") or [],
        },
        "semantic_guards": [
            "Raw source strings are preserved separately from normalized/canonical values.",
            "Superseded source manifestations remain queryable and are not overwritten.",
            "Municipality or proximity matches do not establish facility identity or exposure.",
            "Causal confirmation requires authoritative evidence; proximity is discovery-only.",
            "Human disease records retain suspected/probable/confirmed and case-definition semantics.",
        ],
    })


@router.get("/hazards/events")
def hazard_events(
    family: str | None = Query(default=None),
    status: str | None = Query(default=None),
    municipality_id: str | None = Query(default=None),
    current_only: bool = Query(default=True),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    records = load_records()
    rows = current_records(records) if current_only else records
    if family:
        rows = [row for row in rows if row.family.value == family]
    if status:
        rows = [row for row in rows if row.status.value == status]
    if municipality_id:
        rows = [row for row in rows if row.municipality_id == municipality_id]
    rows = sorted(rows, key=lambda row: row.record_id)
    return JSONResponse({
        "total": len(rows),
        "items": [row.model_dump(mode="json") for row in rows[offset: offset + limit]],
    })


@router.get("/hazards/relationships")
def hazard_relationships(
    predicate: str | None = Query(default=None),
    record_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    rows = load_relationships()
    if predicate:
        rows = [row for row in rows if row.predicate.value == predicate]
    if record_id:
        rows = [row for row in rows if record_id in {row.subject_id, row.object_id}]
    rows = sorted(rows, key=lambda row: row.relationship_id)
    return JSONResponse({
        "total": len(rows),
        "items": [row.model_dump(mode="json") for row in rows[offset: offset + limit]],
    })


@router.get("/hazards/sources")
def hazard_sources() -> JSONResponse:
    return JSONResponse(_source_config())


@router.get("/hazards/integrity")
def hazard_integrity() -> JSONResponse:
    return JSONResponse(graph_integrity())
