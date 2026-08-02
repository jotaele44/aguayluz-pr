"""Bounded ASGI entrypoint for the Phase 0 research-only mycelial surface.

Deployment remains opt-in: use ``research.mycelial.app:app``. The canonical
AguaYLuz application is not modified while this module is under review.
"""
from server.backend.app import app

from .api import router

app.include_router(router)
