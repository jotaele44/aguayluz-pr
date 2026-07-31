"""Read-only API for external environmental provider status."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from server.backend.environmental_providers import (
    NEON_PR_SITES,
    PROVIDERS,
    poll_all,
    poll_provider,
    provider_registry,
)

router = APIRouter(prefix="/environmental-providers", tags=["environmental-providers"])


@router.get("")
def list_environmental_providers() -> JSONResponse:
    return JSONResponse(
        {
            "total": len(PROVIDERS),
            "items": provider_registry(),
            "neon_puerto_rico_sites": list(NEON_PR_SITES),
        }
    )


@router.get("/health")
def environmental_provider_health(
    provider: str | None = Query(default=None),
    live: bool = Query(default=False),
) -> JSONResponse:
    if provider and provider not in PROVIDERS:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unknown_environmental_provider",
                "provider": provider,
                "allowed": sorted(PROVIDERS),
            },
        )
    if not live:
        selected = [
            item
            for item in provider_registry()
            if provider is None or item["code"] == provider
        ]
        return JSONResponse(
            {
                "mode": "configuration_only",
                "external_network_used": False,
                "items": selected,
            }
        )
    payload = (
        {"schema_version": "1.0.0", "providers": [poll_provider(provider)]}
        if provider
        else poll_all(persist=False)
    )
    payload["mode"] = "live"
    payload["external_network_used"] = True
    return JSONResponse(payload)


@router.post("/poll")
def environmental_provider_poll(
    persist: bool = Query(default=False),
) -> JSONResponse:
    return JSONResponse(poll_all(persist=persist))
