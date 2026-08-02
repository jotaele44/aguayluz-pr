"""Bounded ASGI entrypoint enabling the Phase 0 research-only mycelial surface.

Deployment remains opt-in: use ``server.backend.app_mycelial:app``. The standard
application is not silently changed while the module is under review.
"""
from server.backend.app import app
from server.backend.mycelial_api import router

app.include_router(router)
