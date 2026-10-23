"""Read-only staged source audit, unavailable by default."""

import os

from fastapi import APIRouter, HTTPException

from aguayluz.ionosphere import audit_status
from aguayluz.ionosphere_snapshot import snapshot_context

router = APIRouter(tags=["ionosphere"])


@router.get("/ionosphere/status")
def ionosphere_status():
    if os.environ.get("AGUAYLUZ_IONOSPHERE_PREVIEW") != "1":
        raise HTTPException(404, "Ionosphere preview disabled")
    result = audit_status()
    try:
        result["archive"] = snapshot_context()
        result["tec"].update(
            state="ARCHIVED_SNAPSHOT",
            reason="Frozen real capture available; live refresh remains unverified",
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["archive"] = {"state": "BLOCKED", "error": str(exc)}
    return result
