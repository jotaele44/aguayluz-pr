"""Regulatory observation + entity-link API for the AguaYLuz dashboard.

Observation and receipt endpoints are read-only, exposing what
``src/aguayluz/regulatory_db.py`` already persists: ``RegulatoryObservation`` and
``RegulatorySourceReceipt`` rows written by live provider adapters
(``src/aguayluz/regulatory_adapters/``). An observation is one provider's own
statement, never a claim about which AguaLuz facility it describes
(``docs/regulatory_ingestion_framework_v0_1.md``).

Entity-link endpoints add the one write path this framework allows: a human decision
on a candidate ``scripts/build_regulatory_links.py`` proposed. The decide endpoint is
fail-closed at the API layer, not just the JSON-schema layer — it refuses to record
``approved`` while the candidate carries open ``contradictions``, mirroring
``schemas/regulatory_entity_link.schema.json``'s own constraint so a client can never
route around it by skipping client-side validation. Nothing here performs automatic
entity promotion; every ``approved`` row traces to an actor, a timestamp, and a
rationale a human supplied through this endpoint.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aguayluz.regulatory_db import (
    load_regulatory_links,
    load_regulatory_observations,
    load_regulatory_receipts,
    write_regulatory_links,
)
from server.backend import main as legacy

router = APIRouter(tags=["regulatory"])

_DECIDABLE_STATES = frozenset({"approved", "rejected", "needs_review"})


class RegulatoryLinkDecision(BaseModel):
    decision_state: str
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)

_SCOPE_STATEMENT = (
    "Live provider observations only — currently USGS monitoring-location metadata. "
    "An observation is a source's own statement, never a claim about which AguaLuz "
    "facility it describes; entity linkage is a separate, adjudicated step that does "
    "not exist yet."
)


def _observations() -> list[dict[str, Any]]:
    return load_regulatory_observations()


def _receipts() -> list[dict[str, Any]]:
    return load_regulatory_receipts()


def _observation_or_404(observation_id: str) -> dict[str, Any]:
    observation = next(
        (o for o in _observations() if o.get("observation_id") == observation_id), None
    )
    if observation is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "regulatory_observation_not_found", "observation_id": observation_id},
        )
    return observation


def _receipt_or_404(receipt_id: str) -> dict[str, Any]:
    receipt = next((r for r in _receipts() if r.get("receipt_id") == receipt_id), None)
    if receipt is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "regulatory_receipt_not_found", "receipt_id": receipt_id},
        )
    return receipt


def _links() -> list[dict[str, Any]]:
    return load_regulatory_links()


def _link_or_404(candidate_id: str) -> dict[str, Any]:
    link = next((c for c in _links() if c.get("candidate_id") == candidate_id), None)
    if link is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "regulatory_link_not_found", "candidate_id": candidate_id},
        )
    return link


@router.get("/regulatory/summary")
def regulatory_summary() -> JSONResponse:
    observations = _observations()
    receipts = _receipts()
    return JSONResponse({
        "scope": {"statement": _SCOPE_STATEMENT},
        "counts": {"observations": len(observations), "receipts": len(receipts)},
        "provider": dict(sorted(Counter(o["provider"] for o in observations).items())),
        "record_family": dict(
            sorted(Counter(o["record_family"] for o in observations).items())
        ),
        "freshness_state": dict(
            sorted(Counter(o["freshness_state"] for o in observations).items())
        ),
        "evidence_tier": dict(
            sorted(Counter(o["evidence_tier"] for o in observations).items())
        ),
    })


@router.get("/regulatory/observations")
def regulatory_observations(
    provider: str | None = Query(default=None),
    record_family: str | None = Query(default=None),
    freshness_state: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    items = _observations()
    if provider:
        items = [o for o in items if o.get("provider") == provider]
    if record_family:
        items = [o for o in items if o.get("record_family") == record_family]
    if freshness_state:
        items = [o for o in items if o.get("freshness_state") == freshness_state]
    items = sorted(items, key=lambda o: (o["provider"], o["observation_id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return JSONResponse({"total": total, "items": page})


@router.get("/regulatory/observations/{observation_id}")
def regulatory_observation(observation_id: str) -> JSONResponse:
    observation = _observation_or_404(observation_id)
    payload = dict(observation)
    payload["receipt"] = next(
        (r for r in _receipts() if r.get("receipt_id") == observation.get("source_receipt_id")),
        None,
    )
    return JSONResponse(payload)


@router.get("/regulatory/receipts/{receipt_id}")
def regulatory_receipt(receipt_id: str) -> JSONResponse:
    return JSONResponse(_receipt_or_404(receipt_id))


@router.get("/regulatory/links")
def regulatory_links(
    decision_state: str | None = Query(default=None),
    observation_id: str | None = Query(default=None),
    candidate_asset_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    items = _links()
    if decision_state:
        items = [c for c in items if c.get("decision_state") == decision_state]
    if observation_id:
        items = [c for c in items if c.get("observation_id") == observation_id]
    if candidate_asset_id:
        items = [c for c in items if c.get("candidate_asset_id") == candidate_asset_id]
    items = sorted(items, key=lambda c: c["candidate_id"])
    total = len(items)
    page = items[offset : offset + limit]
    return JSONResponse({"total": total, "items": page})


@router.get("/regulatory/links/{candidate_id}")
def regulatory_link(candidate_id: str) -> JSONResponse:
    link = _link_or_404(candidate_id)
    payload = dict(link)
    payload["observation"] = next(
        (o for o in _observations() if o.get("observation_id") == link.get("observation_id")),
        None,
    )
    return JSONResponse(payload)


@router.post("/regulatory/links/{candidate_id}/decide", dependencies=[Depends(legacy._require_key)])
def regulatory_link_decide(candidate_id: str, body: RegulatoryLinkDecision) -> JSONResponse:
    if body.decision_state not in _DECIDABLE_STATES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_decision_state",
                "decision_state": body.decision_state,
                "allowed": sorted(_DECIDABLE_STATES),
            },
        )
    candidate = _link_or_404(candidate_id)
    if body.decision_state == "approved" and candidate.get("contradictions"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "cannot_approve_with_open_contradictions",
                "candidate_id": candidate_id,
                "contradictions": candidate["contradictions"],
            },
        )

    decided = {
        **candidate,
        "decision_state": body.decision_state,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "decided_by": body.actor,
        "decision_rationale": body.rationale,
    }
    write_regulatory_links([decided])
    return JSONResponse(decided)
