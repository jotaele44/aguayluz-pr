"""Read-only environmental exposure graph API."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from aguayluz import DATA_DIR
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


def _read_json(name: str) -> dict[str, Any] | None:
    path = DATA_DIR / name
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_jsonl(name: str) -> list[dict[str, Any]]:
    path = DATA_DIR / name
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _pfas_checkpoint() -> dict[str, Any]:
    occurrence = _read_json("pfas_ucmr5_pr_summary.json")
    manifest = _read_json("pfas_ucmr5_pr_manifest.json")
    sources = _read_jsonl("pfas_source_manifestations.jsonl")
    sites = _read_jsonl("pfas_site_evidence.jsonl")
    rules = _read_jsonl("pfas_regulatory_ledger.jsonl")
    legal = _read_jsonl("pfas_legal_cases.jsonl")

    source_hash_open = sorted(
        str(row.get("source_record_id"))
        for row in sources
        if row.get("source_record_id") and not row.get("byte_sha256")
    )
    primary_docket_open = sum(
        1 for row in legal if str(row.get("primary_docket_state") or "") == "OPEN"
    )
    unresolved = [f"SOURCE_HASH_OPEN:{source_id}" for source_id in source_hash_open]
    if occurrence is None or manifest is None:
        unresolved.append("EPA_UCMR5_PR_DENOMINATOR_NOT_FROZEN")

    materialized_path = DATA_DIR / "pfas_ucmr5_pr.tsv"
    actual_derived_sha = _sha256_file(materialized_path)
    expected_derived_sha = manifest.get("derived_tsv_sha256") if manifest else None
    if actual_derived_sha is None:
        materialization_state = "NOT_MATERIALIZED"
        unresolved.append("UCMR_WHOLE_ROW_APPLICATION_MATERIALIZATION_OPEN")
    elif expected_derived_sha and actual_derived_sha != expected_derived_sha:
        materialization_state = "HASH_MISMATCH"
        unresolved.append("UCMR_WHOLE_ROW_APPLICATION_HASH_MISMATCH")
    else:
        materialization_state = "MATERIALIZED_HASH_MATCH"

    unresolved.extend([
        "PWS_FACILITY_SAMPLE_POINT_GEOMETRY_BINDING_OPEN",
        "DOD_NAVY_DOCUMENT_DENOMINATOR_OPEN",
        "CORPORATE_PRODUCT_SITE_ATTRIBUTION_OPEN",
    ])
    if primary_docket_open:
        unresolved.append("PRIMARY_LITIGATION_DOCKET_FREEZE_OPEN")

    return {
        "certification_state": "OPEN" if unresolved else "PASS",
        "scope": "Puerto Rico PFAS environmental/drinking-water evidence plane",
        "occurrence": occurrence,
        "provenance": {
            "archive_sha256": manifest.get("archive_sha256") if manifest else None,
            "selected_member_sha256": (
                manifest.get("selected_member_sha256") if manifest else None
            ),
            "derived_tsv_sha256": expected_derived_sha,
            "materialized_tsv_sha256": actual_derived_sha,
            "artifact_id": manifest.get("artifact_id") if manifest else None,
            "artifact_digest": manifest.get("artifact_digest") if manifest else None,
        },
        "counts": {
            "source_manifestations": len(sources),
            "source_hashes_open": len(source_hash_open),
            "site_evidence_rows": len(sites),
            "regulatory_rows": len(rules),
            "legal_manifestations": len(legal),
            "primary_legal_dockets_open": primary_docket_open,
        },
        "application_materialization_state": materialization_state,
        "unresolved_material": sorted(set(unresolved)),
        "semantic_guards": [
            "UCMR occurrence is not an MCL compliance finding.",
            "Non-detects are not converted to zero or to the MRL.",
            "Litigation allegations do not establish contaminant-source attribution.",
            "Name/proximity-only evidence cannot establish identity or causation.",
        ],
    }


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
        "pfas": _pfas_checkpoint(),
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
