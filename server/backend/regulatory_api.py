"""Read-only regulatory observation API for the AguaYLuz dashboard.

Exposes what ``src/aguayluz/regulatory_db.py`` already persists:
``RegulatoryObservation`` and ``RegulatorySourceReceipt`` rows written by live
provider adapters (``src/aguayluz/regulatory_adapters/``). Strictly read-only and
non-authoritative, matching the design doc's safety boundary
(``docs/regulatory_ingestion_framework_v0_1.md``): an observation is one provider's
own statement, never a claim about which AguaLuz facility it describes. Entity-link
candidates and adjudicated decisions are a separate, later increment
(``docs/unfinished_implementation_ledger.v1.json``'s ``AYL-008``) — nothing here
promotes an observation into facility identity.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from aguayluz.regulatory_db import load_regulatory_observations, load_regulatory_receipts

router = APIRouter(tags=["regulatory"])

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
