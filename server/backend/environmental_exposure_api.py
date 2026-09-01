"""Read-only environmental exposure graph API."""
from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from aguayluz.environmental_exposure_db import graph_integrity, load

router = APIRouter(tags=["environmental-exposure"])


def _entities() -> list[dict[str, Any]]:
    return load("environmental_entity")


def _observations() -> list[dict[str, Any]]:
    return load("environmental_observation")


def _geometries() -> list[dict[str, Any]]:
    return load("environmental_geometry")


def _relationships() -> list[dict[str, Any]]:
    return load("exposure_relationship")


def _events() -> list[dict[str, Any]]:
    return load("environmental_exposure_event")


@router.get("/environmental-exposure/summary")
def environmental_exposure_summary() -> JSONResponse:
    entities = _entities()
    observations = _observations()
    geometries = _geometries()
    relationships = _relationships()
    events = _events()
    return JSONResponse({
        "scope": {
            "statement": (
                "Temporal environmental source→pathway→receptor graph. Proximity and "
                "nearest-neighbour evidence are discovery-only and cannot establish causation."
            )
        },
        "counts": {
            "entities": len(entities),
            "observations": len(observations),
            "geometries": len(geometries),
            "relationships": len(relationships),
            "events": len(events),
        },
        "entity_kind": dict(sorted(Counter(r["entity_kind"] for r in entities).items())),
        "causal_state": dict(sorted(Counter(r["causal_state"] for r in relationships).items())),
        "predicate": dict(sorted(Counter(r["predicate"] for r in relationships).items())),
        "integrity": graph_integrity(),
    })


@router.get("/environmental-exposure/entities")
def environmental_exposure_entities(
    entity_kind: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    rows = _entities()
    if entity_kind:
        rows = [row for row in rows if row.get("entity_kind") == entity_kind]
    rows = sorted(rows, key=lambda row: row["entity_id"])
    return JSONResponse({"total": len(rows), "items": rows[offset: offset + limit]})


@router.get("/environmental-exposure/relationships")
def environmental_exposure_relationships(
    causal_state: str | None = Query(default=None),
    predicate: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    rows = _relationships()
    if causal_state:
        rows = [row for row in rows if row.get("causal_state") == causal_state]
    if predicate:
        rows = [row for row in rows if row.get("predicate") == predicate]
    if entity_id:
        rows = [row for row in rows if entity_id in {row.get("subject_id"), row.get("object_id")}]
    rows = sorted(rows, key=lambda row: row["relationship_id"])
    return JSONResponse({"total": len(rows), "items": rows[offset: offset + limit]})


@router.get("/environmental-exposure/entities/{entity_id}")
def environmental_exposure_entity(entity_id: str) -> JSONResponse:
    entity = next((row for row in _entities() if row.get("entity_id") == entity_id), None)
    if entity is None:
        raise HTTPException(status_code=404, detail={"error": "environmental_entity_not_found"})
    edges = [
        row for row in _relationships()
        if entity_id in {row.get("subject_id"), row.get("object_id")}
    ]
    observations = [
        row for row in _observations()
        if entity_id in set(row.get("entity_ids") or [])
    ]
    return JSONResponse({"entity": entity, "relationships": edges, "observations": observations})


@router.get("/environmental-exposure/integrity")
def environmental_exposure_integrity() -> JSONResponse:
    return JSONResponse(graph_integrity())
