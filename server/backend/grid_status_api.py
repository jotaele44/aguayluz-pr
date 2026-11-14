"""Read-only, fail-closed grid monitor status contract.

A source snapshot is not proof of a current/complete electricity-grid state.
This surface intentionally exposes NO numeric grid metrics until qualified.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def build_grid_status(
    snapshots: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    max_age_seconds: int = 3600,
) -> dict[str, Any]:
    """Preserve evidence identity; never infer outages, generation, or restoration."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    candidates = [(dt, row) for row in snapshots if isinstance(row, dict)
                  if (dt := _timestamp(row.get("snapshot_ts"))) is not None
                  and dt <= now]
    candidates.sort(key=lambda pair: (pair[0], str(pair[1].get("payload_sha256", ""))), reverse=True)
    latest = candidates[0][1] if candidates else None
    observed_at = candidates[0][0] if candidates else None
    age = (now - observed_at).total_seconds() if observed_at else None
    if not snapshots:
        state = "SOURCE_UNAVAILABLE"
    elif not latest:
        state = "UNVERIFIED"
    elif age is not None and age > max_age_seconds:
        state = "STALE"
    else:
        # This is RAW_UNFROZEN MiLUMA data: age alone cannot certify a live claim.
        state = "UNVERIFIED"
    source = {
        "family": "LUMA_OUTAGES",
        "schema_state": "RAW_UNFROZEN",
        "observation_at": observed_at.isoformat() if observed_at else None,
        "payload_sha256": latest.get("payload_sha256") if latest else None,
        "age_seconds": round(age) if age is not None else None,
        "snapshot_count": len(snapshots),
        "verified_current": False,
    }
    return {
        "contract": "AGUAYLUZ_GRID_STATUS_V1_ALPHA",
        "status": state,
        "as_of_utc": now.isoformat(),
        "source": source,
        "measurements": {
            "customers_without_service": None,
            "demand_mw": None,
            "available_supply_mw": None,
            "reserve_mw": None,
            "hydro_available_mw": None,
        },
        "limitations": [
            "MiLUMA regional snapshots remain RAW_UNFROZEN, not certified municipal outage events.",
            "No current electricity measurements are inferred from snapshots or historical PDFs.",
            "No restoration event is inferred from adjacent snapshots.",
        ],
        "release_certified": False,
    }
