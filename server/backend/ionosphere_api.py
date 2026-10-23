"""Read-only staged source audit, unavailable by default."""
import os

from fastapi import APIRouter, HTTPException

from aguayluz.ionosphere import audit_status

router = APIRouter(tags=["ionosphere"])


@router.get("/ionosphere/status")
def ionosphere_status():
    if os.environ.get("AGUAYLUZ_IONOSPHERE_PREVIEW") != "1":
        raise HTTPException(404, "Ionosphere preview disabled")
    return audit_status()
