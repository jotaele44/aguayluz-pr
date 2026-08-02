"""Research-only lifecycle API and static field console."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from .foundation import ANALYTICS_STATUS, PROHIBITED_ANALYTICS
from .lifecycle import ALLOWED_TRANSITIONS

router = APIRouter(prefix="/research/mycelial/lifecycle", tags=["research-mycelial-lifecycle"])
_UI = Path(__file__).with_name("lifecycle_console.html")


@router.get("/status")
def lifecycle_status() -> JSONResponse:
    return JSONResponse(
        {
            "phase": 1,
            "research_only": True,
            "storage": "append_only",
            "entities": [
                "site",
                "survey_session",
                "lifecycle_observation",
                "media_evidence",
                "environmental_snapshot",
                "state_transition",
            ],
            "states": sorted(ALLOWED_TRANSITIONS),
            "analytics_status": ANALYTICS_STATUS,
            "blocked_predictive_capabilities": sorted(PROHIBITED_ANALYTICS),
        }
    )


@router.get("/transition-policy")
def transition_policy() -> JSONResponse:
    return JSONResponse({key: sorted(value) for key, value in ALLOWED_TRANSITIONS.items()})


@router.get("/console", response_class=HTMLResponse)
def lifecycle_console() -> HTMLResponse:
    return HTMLResponse(_UI.read_text(encoding="utf-8"))


@router.get("/prediction/{capability}", status_code=503)
def prediction_unavailable(capability: str) -> JSONResponse:
    return JSONResponse(
        {
            "status": "model_not_calibrated",
            "available": False,
            "capability": capability,
            "research_only": True,
            "reason": "Phase 1 tracks verified sites and fruiting observations; it does not predict mushroom locations.",
        },
        status_code=503,
    )
