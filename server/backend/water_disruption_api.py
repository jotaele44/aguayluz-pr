"""FastAPI surface for Agua y Luz shadow water-disruption operations."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from server.backend.water_disruption import WaterIncidentService

router = APIRouter(prefix="/water-disruption", tags=["water-disruption"])
service = WaterIncidentService(Path(os.environ.get("AGUAYLUZ_DATA_DIR", ".aguayluz")) / "water-disruption")


class ValidationRequest(BaseModel):
    candidate: dict[str, Any]
    authoritative_scope_match: bool = False
    independent_source_count: int = 0
    reviewer_approved: bool = False
    public_infrastructure: bool = True
    location_resolved: bool = True
    stale: bool = False
    reviewer: str


class TransitionRequest(BaseModel):
    to_state: str
    reason: str


class RetractionRequest(BaseModel):
    candidate_id: str
    reason: str


class MergeRequest(BaseModel):
    source_incident_ids: list[str]
    reason: str


class SplitRequest(BaseModel):
    child_dedup_keys: list[str]
    reason: str


@router.get("/console", response_class=HTMLResponse)
def console() -> str:
    return """<!doctype html><html><head><meta charset='utf-8'><title>Agua y Luz Water Incidents</title><style>body{font-family:system-ui;margin:2rem;max-width:1100px}nav a{margin-right:1rem}.badge{padding:.2rem .5rem;border:1px solid #999;border-radius:99px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.card{border:1px solid #ccc;border-radius:.6rem;padding:1rem}</style></head><body><h1>Water Incident Validation</h1><p><span class='badge'>Shadow mode</span> Notifications and production exports are disabled.</p><nav><a href='/water-disruption/validation-queue'>Validation queue</a><a href='/water-disruption/incidents'>Incidents</a></nav><div class='grid'><section class='card'><h2>Evidence view</h2><p>Each intake receipt preserves candidate ID, envelope hash, provenance, schema decision, and replay state.</p></section><section class='card'><h2>Map view</h2><p>Municipality and asset hints are shown when present. Missing or approximate geometry remains unresolved; the application does not fabricate coordinates.</p></section></div></body></html>"""


@router.post("/intake")
def intake(envelope: dict[str, Any], idempotency_key: str = Header(alias="Idempotency-Key"), shadow_mode: str = Header(default="true", alias="X-Shadow-Mode")) -> dict[str, Any]:
    if shadow_mode.lower() != "true":
        raise HTTPException(status_code=409, detail="shadow_mode_required")
    try:
        result = service.intake(envelope, idempotency_key)
        return {**result, "shadow_mode": True, "notifications_enabled": False, "production_promotion_enabled": False}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/intake/{candidate_id}")
def intake_status(candidate_id: str) -> dict[str, Any]:
    item = service.store.latest("intake_receipts", "candidate_id", candidate_id)
    if not item:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    return item


@router.get("/validation-queue")
def validation_queue() -> dict[str, Any]:
    receipts = service.store.read("intake_receipts")
    decisions = {row["candidate_id"] for row in service.store.read("validation_events")}
    items = [row for row in receipts if row["candidate_id"] not in decisions]
    return {"shadow_mode": True, "total": len(items), "items": items}


@router.post("/validation/{candidate_id}")
def validate(candidate_id: str, request: ValidationRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    if request.candidate.get("candidate_id") != candidate_id:
        raise HTTPException(status_code=422, detail="candidate_id_mismatch")
    decision = service.validation_policy(request.candidate, authoritative_scope_match=request.authoritative_scope_match, independent_source_count=request.independent_source_count, reviewer_approved=request.reviewer_approved, public_infrastructure=request.public_infrastructure, location_resolved=request.location_resolved, stale=request.stale)
    return service.validate(request.candidate, decision, request.reviewer, idempotency_key)


@router.get("/incidents")
def incidents() -> dict[str, Any]:
    ids = sorted({row["incident_id"] for row in service.store.read("incidents")})
    return {"shadow_mode": True, "notifications_enabled": False, "total": len(ids), "items": [service.current_incident(value) for value in ids]}


@router.get("/incidents/{incident_id}")
def incident(incident_id: str) -> dict[str, Any]:
    try:
        return service.current_incident(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="incident_not_found") from exc


@router.post("/incidents/{incident_id}/transition")
def transition(incident_id: str, request: TransitionRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    try:
        return service.transition(incident_id, request.to_state, request.reason, idempotency_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="incident_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/incidents/{incident_id}/merge")
def merge(incident_id: str, request: MergeRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    return service.merge(incident_id, request.source_incident_ids, request.reason, idempotency_key)


@router.post("/incidents/{incident_id}/split")
def split(incident_id: str, request: SplitRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    return service.split(incident_id, request.child_dedup_keys, request.reason, idempotency_key)


@router.post("/retractions")
def retract(request: RetractionRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    return service.retract(request.candidate_id, request.reason, idempotency_key)
