"""Independent ASGI application for the Phase 0 research surface.

Importing this module must never mutate ``server.backend.app:app``.
"""
from fastapi import FastAPI

from .api import router


def create_app() -> FastAPI:
    application = FastAPI(
        title="AguaYLuz fungal occurrence research foundation",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.include_router(router)
    return application


app = create_app()
