"""Source-health rules shared by adapters and admin/API surfaces."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import HealthState, SourceHealth


def evaluate_health(
    source_family_id: str,
    *,
    now: datetime | None = None,
    last_check: datetime | None = None,
    last_success: datetime | None = None,
    last_change: datetime | None = None,
    current_sha256: str | None = None,
    schema_fingerprint: str | None = None,
    record_count: int | None = None,
    expected_nonzero: bool = False,
    stale_after: timedelta | None = None,
    error_class: str | None = None,
    changed: bool = False,
) -> SourceHealth:
    """Evaluate a source fail-closed.

    HTTP success is deliberately not an input: transport success without schema
    and record validation cannot produce HEALTHY.
    """
    now = now or datetime.now(timezone.utc)
    if error_class:
        mapping = {
            "RATE_LIMITED": HealthState.RATE_LIMITED,
            "AUTH_FAILED": HealthState.AUTH_FAILED,
            "CONTENT_TYPE_CHANGED": HealthState.CONTENT_TYPE_CHANGED,
            "SCHEMA_DRIFT": HealthState.SCHEMA_DRIFT,
            "PARSE_FAILED": HealthState.PARSE_FAILED,
            "VALIDATION_FAILED": HealthState.VALIDATION_FAILED,
            "SOURCE_REMOVED": HealthState.SOURCE_REMOVED,
            "IDENTITY_CONFLICT": HealthState.IDENTITY_CONFLICT,
        }
        state = mapping.get(error_class, HealthState.FETCH_FAILED)
    elif expected_nonzero and record_count == 0:
        state = HealthState.VALIDATION_FAILED
        error_class = "UNEXPECTED_ZERO_ROWS"
    elif stale_after and (last_success is None or now - last_success > stale_after):
        state = HealthState.STALE
    elif changed:
        state = HealthState.NEW_MANIFESTATION
    else:
        state = HealthState.HEALTHY if last_success else HealthState.NO_CHANGE

    return SourceHealth(
        source_family_id=source_family_id,
        state=state,
        last_check=last_check,
        last_success=last_success,
        last_change=last_change,
        current_sha256=current_sha256,
        schema_fingerprint=schema_fingerprint,
        record_count=record_count,
        error_class=error_class,
    )
