"""FastAPI surface for Agua y Luz shadow water-disruption operations."""
from __future__ import annotations

import html
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


def _control_plane_html(control: dict[str, Any]) -> str:
    coverage = control.get("coverage_summary", {})
    current = control.get("current_condition", {})
    synchronization = control.get("synchronization", {})
    balance = control.get("water_balance", {})
    missing = current.get("missing_required_metrics", [])
    hypotheses = control.get("hypotheses", [])
    contradictions = control.get("contradictions", [])

    hypothesis_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('cause', 'unknown')))}</td>"
        f"<td>{html.escape(str(item.get('state', 'unknown')))}</td>"
        f"<td>{html.escape(str(item.get('confidence', '')))}</td>"
        f"<td>{html.escape(str(item.get('basis', '')))}</td>"
        "</tr>"
        for item in hypotheses
    ) or "<tr><td colspan='4'>No hypotheses materialized.</td></tr>"
    contradiction_rows = "".join(
        "<li>"
        f"{html.escape(str(item.get('type', 'unknown')))} "
        f"({html.escape(str(item.get('record_count', 0)))})"
        "</li>"
        for item in contradictions
    ) or "<li>None materialized.</li>"
    missing_text = ", ".join(html.escape(str(value)) for value in missing) or "None"

    return f"""
    <section class='card wide'>
      <h2>Laguna Cartagena current-condition control plane</h2>
      <p><span class='badge'>Unknown-safe</span> Direct current condition:
        <strong>{html.escape(str(current.get('status', 'unknown')))}</strong>.
        No alert or control action is generated from stale, distant, or unsynchronized evidence.
      </p>
      <div class='metrics'>
        <div><strong>{coverage.get('source_count', 0)}</strong><span>coverage sources</span></div>
        <div><strong>{coverage.get('direct_current_source_count', 0)}</strong><span>direct current sources</span></div>
        <div><strong>{coverage.get('historical_only_source_count', 0)}</strong><span>historical-only sources</span></div>
        <div><strong>{current.get('eligible_observation_count', 0)}</strong><span>eligible current observations</span></div>
      </div>
      <p><strong>Missing direct metrics:</strong> {missing_text}</p>
      <p><strong>Synchronization:</strong> {html.escape(str(synchronization.get('status', 'unknown')))}
         · <strong>Water balance:</strong> {html.escape(str(balance.get('status', 'not_computed')))}</p>
      <table>
        <thead><tr><th>Cause</th><th>State</th><th>Confidence</th><th>Basis</th></tr></thead>
        <tbody>{hypothesis_rows}</tbody>
      </table>
      <h3>Contradictions and exclusions</h3>
      <ul>{contradiction_rows}</ul>
      <p class='muted'>Observation intake uses the existing POST /water-disruption/intake route with
      schema_version=aguayluz.laguna-cartagena-observation/v0.2 and X-Shadow-Mode=true.</p>
    </section>
    """


@router.get("/console", response_class=HTMLResponse)
def console() -> str:
    control = service.laguna_cartagena_summary()
    control_html = _control_plane_html(control)
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>Agua y Luz Water Incidents</title><style>
body{{font-family:system-ui;margin:2rem;max-width:1100px;background:#020617;color:#cbd5e1}}
nav a{{margin-right:1rem;color:#38bdf8}}.badge{{padding:.2rem .5rem;border:1px solid #64748b;border-radius:99px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}.card{{border:1px solid #334155;border-radius:.6rem;padding:1rem;background:#0f172a}}
.wide{{grid-column:1/-1}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.75rem;margin:1rem 0}}
.metrics div{{border:1px solid #334155;border-radius:.5rem;padding:.75rem}}.metrics strong{{display:block;font-size:1.3rem;color:#f8fafc}}
.metrics span,.muted{{font-size:.8rem;color:#94a3b8}}table{{width:100%;border-collapse:collapse;margin-top:.75rem}}
th,td{{border:1px solid #334155;padding:.45rem;text-align:left;vertical-align:top}}h1,h2,h3{{color:#f8fafc}}
@media(max-width:800px){{.grid,.metrics{{grid-template-columns:1fr}}}}
</style></head><body><h1>Water Incident Validation</h1>
<p><span class='badge'>Shadow mode</span> Notifications and production exports are disabled.</p>
<nav><a href='/water-disruption/validation-queue'>Validation queue</a><a href='/water-disruption/incidents'>Incidents + Laguna control plane</a></nav>
<div class='grid'><section class='card'><h2>Evidence view</h2><p>Each intake receipt preserves candidate or observation ID, envelope hash, provenance, schema decision, and replay state.</p></section>
<section class='card'><h2>Map view</h2><p>Municipality and asset hints are shown when present. Missing or approximate geometry remains unresolved; the application does not fabricate coordinates.</p></section>
{control_html}</div></body></html>"""


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
        item = service.store.latest(
            "laguna_cartagena_intake_receipts",
            "observation_id",
            candidate_id,
        )
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
    return {
        "shadow_mode": True,
        "notifications_enabled": False,
        "total": len(ids),
        "items": [service.current_incident(value) for value in ids],
        "laguna_cartagena": service.laguna_cartagena_summary(),
    }


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
