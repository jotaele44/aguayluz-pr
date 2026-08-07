"""Research-only fungal occurrence evidence API.

All ecological analytics remain unavailable until a separately reviewed
calibration phase is installed.
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
from .staging import (
    CAPABILITY_CLASSIFICATION,
    FEATURE_FLAG_ENV,
    STAGING_EXPIRES_ON,
    TRACKING_REFERENCE,
)

router = APIRouter(prefix="/research/mycelial", tags=["research-mycelial"])


@router.get("/status")
def status() -> JSONResponse:
    return JSONResponse(
        {
            "module": "fungal_occurrence_foundation",
            "project_umbrella": "mycelial_research",
            "phase": 0,
            "schema_version": SCHEMA_VERSION,
            "research_only": RESEARCH_ONLY,
            "analytics_status": ANALYTICS_STATUS,
            "capability_classification": CAPABILITY_CLASSIFICATION,
            "tracking_reference": TRACKING_REFERENCE,
            "staging_expires_on": STAGING_EXPIRES_ON.isoformat(),
            "feature_flag": FEATURE_FLAG_ENV,
            "enabled_capabilities": [
                "fungal_occurrence_ingest",
                "provenance_ledger",
                "dataset_registry",
                "exact_replay_idempotency",
                "duplicate_candidate_linking",
                "adjudication",
                "supersession",
                "sensitive_coordinate_controls",
                "run_receipts",
            ],
            "blocked_capabilities": sorted(PROHIBITED_ANALYTICS),
        }
    )


@router.get("/analytics/{capability}", status_code=503)
def unavailable_analytics(capability: str) -> JSONResponse:
    return JSONResponse(analytics_unavailable(capability), status_code=503)
