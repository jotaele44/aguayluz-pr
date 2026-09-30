"""EPA SDWIS adapter for canonical water-health hazard records.

SDWIS violations are regulatory events. A public-notification tier on a
violation does not, by itself, prove that a boil-water, do-not-drink, or
do-not-use advisory was issued. Notice/action manifestations must be bound
separately.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from aguayluz.hazard_plane import (
    HazardFamily,
    HazardRecord,
    RecordKind,
    RecordStatus,
)

MICROBIAL_RULE_GROUPS = frozenset({"100", "110", "111", "120", "130", "140"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_sdwis_datetime(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw or raw.lower() == "null":
        return None
    normalized = raw.replace(" ", "T")
    if "T" not in normalized:
        normalized += "T00:00:00"
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def row_digest(row: dict[str, Any]) -> str:
    encoded = json.dumps(
        row,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def canonical_event_id(row: dict[str, Any]) -> str:
    pwsid = _text(row.get("pwsid")).upper()
    violation_id = _text(row.get("violation_id"))
    if not pwsid or not violation_id:
        raise ValueError("SDWIS violation requires pwsid and violation_id")
    return f"EPA_SDWIS:{pwsid}:VIOLATION:{violation_id}"


def stable_record_id(row: dict[str, Any]) -> str:
    return f"{canonical_event_id(row)}:REV:{row_digest(row)[:20]}"


def is_health_based(row: dict[str, Any]) -> bool:
    return _text(row.get("is_health_based_ind")).upper() == "Y"


def public_notification_tier(row: dict[str, Any]) -> int | None:
    return _int_or_none(row.get("public_notification_tier"))


def is_tier1_microbial_health_violation(row: dict[str, Any]) -> bool:
    return (
        is_health_based(row)
        and public_notification_tier(row) == 1
        and _text(row.get("rule_group_code")) in MICROBIAL_RULE_GROUPS
    )


def record_status(row: dict[str, Any]) -> RecordStatus:
    violation_status = _text(row.get("violation_status")).upper()
    compliance_status = _text(row.get("compliance_status_code")).upper()
    if violation_status == "RESOLVED" or compliance_status == "R":
        return RecordStatus.TERMINATED
    if violation_status == "ARCHIVED":
        return RecordStatus.INACTIVE
    if violation_status in {"ADDRESSED", "UNADDRESSED"}:
        return RecordStatus.ACTIVE
    if compliance_status:
        return RecordStatus.ACTIVE
    return RecordStatus.UNRESOLVED


def hazard_type(row: dict[str, Any]) -> str:
    if is_tier1_microbial_health_violation(row):
        return "SDWA_TIER1_MICROBIAL_HEALTH_VIOLATION"
    if is_health_based(row):
        return "SDWA_HEALTH_BASED_VIOLATION"
    return "SDWA_VIOLATION"


def normalize(
    row: dict[str, Any],
    manifestation_id: str,
    *,
    geo_rows: list[dict[str, Any]] | None = None,
    municipality_name: str | None = None,
    geography_manifestation_ids: list[str] | None = None,
    supersedes_record_id: str | None = None,
) -> HazardRecord:
    pwsid = _text(row.get("pwsid")).upper()
    violation_id = _text(row.get("violation_id"))
    event_id = canonical_event_id(row)
    tier = public_notification_tier(row)
    acute_signal = is_tier1_microbial_health_violation(row)
    label = (
        "Tier 1 microbial health-based SDWA violation"
        if acute_signal
        else "Health-based SDWA violation"
        if is_health_based(row)
        else "SDWA violation"
    )
    title_raw = _text(row.get("violation_code")) or violation_id

    return HazardRecord(
        record_id=stable_record_id(row),
        canonical_event_id=event_id,
        record_kind=RecordKind.EVENT,
        family=HazardFamily.WATER_HEALTH,
        hazard_type=hazard_type(row),
        source_authority="EPA",
        source_record_id=violation_id,
        manifestation_id=manifestation_id,
        title_raw=title_raw,
        description_raw=None,
        normalized_label=label,
        status=record_status(row),
        observed_from=parse_sdwis_datetime(row.get("compl_per_begin_date")),
        observed_to=parse_sdwis_datetime(row.get("compl_per_end_date")),
        water_system_id=pwsid,
        geography_basis="SDWIS_GEOGRAPHIC_AREA" if geo_rows else "PWSID_ONLY",
        geometry_precision="PWS_SERVICE_AREA_TEXT_ONLY" if geo_rows else "NONE",
        supersedes_record_id=supersedes_record_id,
        raw_attributes={
            "source_row": row,
            "geographic_area_rows": geo_rows or [],
            "geography_manifestation_ids": geography_manifestation_ids or [],
            "municipality_name": municipality_name,
            "health_based": is_health_based(row),
            "public_notification_tier": tier,
            "tier1_microbial_health_signal": acute_signal,
            "advisory_issued": False,
            "advisory_semantics": (
                "VIOLATION_RECORD_NOT_PROOF_OF_BOIL_WATER_DO_NOT_DRINK_OR_DO_NOT_USE_NOTICE"
            ),
            "federal_reporting_semantics": (
                "SDWIS_ECHO_COMPLIANCE_DATA_MAY_LAG_SOURCE_EVENTS_BY_MULTIPLE_MONTHS"
            ),
        },
    )
