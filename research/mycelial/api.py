"""Research-only mycelial evidence API.

All ecological analytics are intentionally unavailable until a separately
reviewed calibration phase is installed.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .foundation import (
    ANALYTICS_STATUS,
    PROHIBITED_ANALYTICS,
    RESEARCH_ONLY,
    SCHEMA_VERSION,
    analytics_unavailable,
)

router = APIRouter(prefix="/research/mycelial", tags=["research-mycelial"])


@router.get("/status")
def status() -> JSONResponse:
    return JSONResponse(
        {
            "module": "mycelial_foundation",
            "phase": 0,
            "schema_version": SCHEMA_VERSION,
            "research_only": RESEARCH_ONLY,
            "analytics_status": ANALYTICS_STATUS,
            "enabled_capabilities": [
                "occurrence_ingest",
                "provenance_ledger",
                "dataset_registry",
                "deduplication",
                "adjudication",
                "sensitive_coordinate_controls",
                "run_receipts",
            ],
            "blocked_capabilities": sorted(PROHIBITED_ANALYTICS),
        }
    )


@router.get("/analytics/{capability}", status_code=503)
def unavailable_analytics(capability: str) -> JSONResponse:
    return JSONResponse(analytics_unavailable(capability), status_code=503)
