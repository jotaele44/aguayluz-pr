"""Read-only staged source audit, unavailable by default."""

import hashlib
import json
import os

from fastapi import APIRouter, HTTPException

from aguayluz.ionosphere import audit_status
from aguayluz.ionosphere_snapshot import snapshot_context
from aguayluz.ionosphere_transport import ROOT, load_reference_coverage

router = APIRouter(tags=["ionosphere"])


@router.get("/ionosphere/status")
def ionosphere_status():
    if os.environ.get("AGUAYLUZ_IONOSPHERE_PREVIEW") != "1":
        raise HTTPException(404, "Ionosphere preview disabled")
    result = audit_status()
    try:
        audit_raw = (ROOT / "roti_provider_audit.json").read_bytes()
        if (
            hashlib.sha256(audit_raw).hexdigest()
            != "cd9fc29dd8d1be1a5d36b06c97f617257d545ef9daad7e39d390a49a33741b71"
        ):
            raise ValueError("ROTI audit receipt changed")
        result["roti"]["audit"] = json.loads(audit_raw)
    except (OSError, ValueError) as exc:
        result["roti"]["audit_error"] = str(exc)
    try:
        result["archive"] = snapshot_context()
        result["archive"]["reference_coverage"] = load_reference_coverage()
        result["tec"].update(
            state="ARCHIVED_SNAPSHOT",
            reason="Frozen real capture available; live refresh remains unverified",
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["archive"] = {"state": "BLOCKED", "error": str(exc)}
    return result
