"""EPA SDWIS drinking-water violation adapter for the canonical hazard plane.

This adapter normalizes already-fetched SDWA_VIOLATIONS_ENFORCEMENT rows.  It keeps
Puerto Rico Department of Health annual-report manifestations separate from later
federal SDWIS snapshots: federal rows reconcile identity and revision state; they do
not overwrite what a state annual report published for its own frozen reporting year.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus


def row_digest(row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _value(row: dict[str, Any], *names: str) -> str:
    normalized = {str(key).strip().upper(): value for key, value in row.items()}
    for name in names:
        value = normalized.get(name.upper())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def canonical_event_id(row: dict[str, Any]) -> str:
    pwsid = _value(row, "PWSID")
    violation_id = _value(row, "VIOLATION_ID")
    if pwsid and violation_id:
        return f"EPA_SDWIS_VIOLATION:{pwsid}:{violation_id}"
    return f"EPA_SDWIS_VIOLATION_UNRESOLVED:{row_digest(row)[:24]}"


def stable_record_id(row: dict[str, Any]) -> str:
    return f"{canonical_event_id(row)}:REV:{row_digest(row)[:20]}"


def _status(row: dict[str, Any]) -> RecordStatus:
    raw = _value(
        row,
        "VIOLATION_STATUS",
        "VIOLATION_STATUS_CODE",
        "COMPLIANCE_STATUS",
        "COMPLIANCE_STATUS_CODE",
    ).casefold()
    if not raw:
        return RecordStatus.UNRESOLVED
    if any(token in raw for token in ("unresolved", "unaddressed", "open", "active")):
        return RecordStatus.ACTIVE
    if any(token in raw for token in ("resolved", "addressed", "returned to compliance", "rtc")):
        return RecordStatus.INACTIVE
    if any(token in raw for token in ("archived", "historical")):
        return RecordStatus.FINAL
    return RecordStatus.UNRESOLVED


def _hazard_type(row: dict[str, Any]) -> str:
    category = _value(
        row,
        "VIOLATION_CATEGORY_CODE",
        "VIOLATION_CATEGORY",
        "VIOLATION_CATEGORY_NAME",
    ).upper()
    health_based = _value(row, "IS_HEALTH_BASED_IND", "IS_HEALTH_BASED").upper()
    combined = f"{category} {_value(row, 'VIOLATION_NAME', 'VIOLATION_TYPE_NAME')}".upper()

    if "MRDL" in combined:
        return "DRINKING_WATER_MRDL_VIOLATION"
    if re.search(r"\bMCL\b", combined):
        return "DRINKING_WATER_MCL_VIOLATION"
    if "TREATMENT" in combined or re.search(r"\bTT\b", combined):
        return "DRINKING_WATER_TREATMENT_TECHNIQUE_VIOLATION"
    if "PUBLIC" in combined and "NOTIF" in combined:
        return "DRINKING_WATER_PUBLIC_NOTIFICATION_VIOLATION"
    if "MONITOR" in combined or "REPORT" in combined or category in {"MR", "MON", "RPT"}:
        return "DRINKING_WATER_MONITORING_REPORTING_VIOLATION"
    if health_based in {"Y", "YES", "TRUE", "1"}:
        return "DRINKING_WATER_HEALTH_BASED_VIOLATION"
    return "DRINKING_WATER_COMPLIANCE_VIOLATION"


def normalize(
    row: dict[str, Any],
    manifestation_id: str,
    *,
    supersedes_record_id: str | None = None,
) -> HazardRecord:
    """Normalize one SDWIS violation row without converting compliance failures into exposure."""
    pwsid = _value(row, "PWSID")
    violation_id = _value(row, "VIOLATION_ID")
    facility_id = _value(row, "FACILITY_ID")
    begin = _date(_value(row, "NON_COMPL_PER_BEGIN_DATE"))
    end = _date(_value(row, "NON_COMPL_PER_END_DATE"))
    hazard_type = _hazard_type(row)
    system_name = _value(row, "PWS_NAME")
    violation_name = _value(row, "VIOLATION_NAME", "VIOLATION_TYPE_NAME")
    title = violation_name or hazard_type.replace("_", " ").title()
    if system_name:
        title = f"{system_name}: {title}"

    return HazardRecord(
        record_id=stable_record_id(row),
        canonical_event_id=canonical_event_id(row),
        record_kind=RecordKind.EVENT,
        family=HazardFamily.WATER_HEALTH,
        hazard_type=hazard_type,
        source_authority="US EPA",
        source_record_id=(
            f"{pwsid}:{violation_id}" if pwsid and violation_id else stable_record_id(row)
        ),
        manifestation_id=manifestation_id,
        title_raw=title,
        description_raw=_value(row, "VIOLATION_DESC", "VIOLATION_DESCRIPTION") or None,
        normalized_label=violation_name or None,
        status=_status(row),
        observed_from=begin,
        observed_to=end,
        reported_at=_date(_value(row, "CALCULATED_RTC_DATE", "RTC_DATE")),
        water_system_id=f"EPA_PWSID:{pwsid}" if pwsid else None,
        facility_id=(
            f"EPA_PWSID:{pwsid}:FACILITY:{facility_id}"
            if pwsid and facility_id
            else None
        ),
        geography_basis="EPA_SDWIS_STABLE_ID" if pwsid else "EPA_SDWIS_IDENTITY_UNRESOLVED",
        geometry_precision="NONE_UNLESS_INDEPENDENTLY_BOUND",
        supersedes_record_id=supersedes_record_id,
        raw_attributes={
            "submission_year_quarter": _value(row, "SUBMISSIONYEARQUARTER") or None,
            "pwsid": pwsid or None,
            "pws_name": system_name or None,
            "violation_id": violation_id or None,
            "facility_id": facility_id or None,
            "violation_category": _value(
                row,
                "VIOLATION_CATEGORY_CODE",
                "VIOLATION_CATEGORY",
                "VIOLATION_CATEGORY_NAME",
            ) or None,
            "is_health_based_ind": _value(row, "IS_HEALTH_BASED_IND", "IS_HEALTH_BASED") or None,
            "public_notification_tier": _value(row, "PUBLIC_NOTIFICATION_TIER") or None,
            "contaminant_code": _value(row, "CONTAMINANT_CODE") or None,
            "rule_code": _value(row, "RULE_CODE") or None,
            "violation_measure": _value(row, "VIOL_MEASURE", "VIOLATION_MEASURE") or None,
            "unit_of_measure": _value(row, "UNIT_OF_MEASURE") or None,
            "federal_mcl": _value(row, "FEDERAL_MCL") or None,
            "state_mcl": _value(row, "STATE_MCL") or None,
            "latest_enforcement_id": _value(row, "LATEST_ENFORCEMENT_ID") or None,
            "rtc_enforcement_id": _value(row, "RTC_ENFORCEMENT_ID") or None,
            "source_row_sha256": row_digest(row),
            "source_row": row,
            "semantic_guardrail": (
                "Compliance/monitoring/public-notification violations do not by themselves "
                "establish contaminant exposure or measured exceedance."
            ),
        },
    )
