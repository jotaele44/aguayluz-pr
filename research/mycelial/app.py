"""Independent, fail-closed ASGI app for the Phase 0 research surface.

Importing this module never mutates ``server.backend.app:app``. The exported
ASGI object registers research routes only when the bounded staging feature
flag is explicitly enabled and the staging window has not expired.
"""
from __future__ import annotations

from datetime import date

from fastapi import FastAPI

from .api import router
from .staging import (
    CAPABILITY_CLASSIFICATION,
    FEATURE_FLAG_ENV,
    STAGING_EXPIRES_ON,
    TRACKING_REFERENCE,
    feature_flag_enabled,
    staging_window_open,
)


def create_app(
    *,
    enable_research_routes: bool = True,
    today: date | None = None,
) -> FastAPI:
    """Build an isolated app; explicit factory use is an operator opt-in."""
    application = FastAPI(
        title="AguaYLuz fungal occurrence research foundation",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    window_open = staging_window_open(today)
    routes_enabled = bool(enable_research_routes and window_open)
    application.state.capability_classification = CAPABILITY_CLASSIFICATION
    application.state.tracking_reference = TRACKING_REFERENCE
    application.state.staging_expires_on = STAGING_EXPIRES_ON.isoformat()
    application.state.feature_flag = FEATURE_FLAG_ENV
    application.state.research_routes_enabled = routes_enabled
    if routes_enabled:
        application.include_router(router)
    return application


app = create_app(enable_research_routes=feature_flag_enabled())
