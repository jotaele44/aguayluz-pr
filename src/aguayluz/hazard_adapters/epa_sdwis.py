"""EPA SDWIS drinking-water violation adapter for the canonical hazard plane.

SDWIS VIOLATION rows are regulatory observations. Public-notification tier expresses
notice urgency; it does not by itself establish a consumer instruction such as
"boil water", "do not drink", or "do not use". Those advisory semantics require an
explicit source notice and are intentionally not inferred here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus

CONSUMER_ACTION_UNVERIFIED = "UNVERIFIED_WITHOUT_EXPLICIT_PUBLIC_NOTICE"


def row_digest(row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def canonical_event_id(row: dict[str, Any]) -> str:
    pwsid = str(row.get("pwsid") or "").strip().upper()
    violation_id = str(row.get("violation_id") or "").strip()
    if pwsid and violation_id:
        return f"EPA_SDWIS_VIOLATION:{pwsid}:{violation_id}"
    return f"EPA_SDWIS_UNRESOLVED:{row_digest(row)[:24]}"


def stable_record_id(row: dict[str, Any]) -> str:
    return f"{canonical_event_id(row)}:REV:{row_digest(row)[:20]}"


def _date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.casefold() == "null":
        return None
    text = text.replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize(
    row: dict[str, Any],
    manifestation_id: str,
    *,
    supersedes_record_id: str | None = None,
) -> HazardRecord:
    """Normalize one SDWIS VIOLATION row without inventing advisory semantics."""
    pwsid = str(row.get("pwsid") or "").strip().upper()
    violation_id = str(row.get("violation_id") or "").strip()
    health_raw = str(row.get("is_health_based_ind") or "").strip().upper()
    health_based = health_raw == "Y"
    compliance_raw = str(row.get("compliance_status_code") or "").strip().upper()
    tier_raw = str(row.get("public_notification_tier") or "").strip()

    if compliance_raw == "R":
        status = RecordStatus.TERMINATED
    elif compliance_raw:
        status = RecordStatus.ACTIVE
    else:
        status = RecordStatus.UNRESOLVED

    hazard_type = (
        "DRINKING_WATER_HEALTH_BASED_VIOLATION"
        if health_based
        else "DRINKING_WATER_REGULATORY_VIOLATION"
    )
    title = (
        "EPA SDWIS health-based drinking-water violation"
        if health_based
        else "EPA SDWIS drinking-water regulatory violation"
    )

    return HazardRecord(
        record_id=stable_record_id(row),
        canonical_event_id=canonical_event_id(row),
        record_kind=RecordKind.OBSERVATION,
        family=HazardFamily.WATER_HEALTH,
        hazard_type=hazard_type,
        source_authority="EPA",
        source_record_id=f"{pwsid}:{violation_id}" if pwsid and violation_id else stable_record_id(row),
        manifestation_id=manifestation_id,
        title_raw=title,
        description_raw=None,
        normalized_label=str(row.get("contaminant_code") or "").strip() or None,
        status=status,
        observed_from=_date(row.get("compl_per_begin_date")),
        observed_to=_date(row.get("compl_per_end_date")),
        reported_at=None,
        issued_at=None,
        geography_basis="EPA_SDWIS_PWSID_STABLE_ID_UNBOUND_TO_FEDERATION_WATER_SYSTEM",
        geometry_precision="NONE_UNLESS_INDEPENDENTLY_BOUND",
        supersedes_record_id=supersedes_record_id,
        raw_attributes={
            "pwsid": pwsid or None,
            "violation_id": violation_id or None,
            "violation_code": row.get("violation_code"),
            "violation_category_code": row.get("violation_category_code"),
            "rule_group_code": row.get("rule_group_code"),
            "contaminant_code": row.get("contaminant_code"),
            "is_health_based_ind": row.get("is_health_based_ind"),
            "public_notification_tier": row.get("public_notification_tier"),
            "tier1_requires_immediate_public_notice": tier_raw == "1",
            "consumer_action": CONSUMER_ACTION_UNVERIFIED,
            "boil_water_inferred": False,
            "compliance_status_code": row.get("compliance_status_code"),
            "population_served_count": row.get("population_served_count"),
            "source_row_sha256": row_digest(row),
            "source_row": row,
        },
    )
