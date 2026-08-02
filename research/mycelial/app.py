"""Bounded ASGI entrypoint for research-only mycelial Phase 0 and Phase 1."""
from server.backend.app import app

from .api import router as foundation_router
from .lifecycle_api import router as lifecycle_router

app.include_router(foundation_router)
app.include_router(lifecycle_router)
