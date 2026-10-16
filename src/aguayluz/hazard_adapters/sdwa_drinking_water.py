"""EPA SDWIS drinking-water violation adapter for the canonical hazard plane.

SDWA_VIOLATIONS_ENFORCEMENT is a violation/enforcement association table: one
violation can legitimately appear on multiple source rows because it has multiple
enforcement actions.  This adapter therefore separates SOURCE ROW identity from
VIOLATION SNAPSHOT identity before creating canonical hazard records.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Iterable

from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus

ENFORCEMENT_FIELDS = {
    "ENFORCEMENT_ID",
    "ENFORCEMENT_DATE",
    "ENFORCEMENT_ACTION_TYPE_CODE",
    "ENF_ACTION_CATEGORY",
    "ENF_ORIGINATOR_CODE",
    "ENF_FIRST_REPORTED_DATE",
    "ENF_LAST_REPORTED_DATE",
}
_INTERNAL_NONMATERIAL_FIELDS = {
    "_SOURCE_ROW_COUNT",
    "_SOURCE_ROW_SHA256S",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def row_digest(row: dict[str, Any]) -> str:
    return sha256(_canonical_json(row).encode("utf-8")).hexdigest()


def _normalized_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).strip().upper(): value for key, value in row.items()}


def _value(row: dict[str, Any], *names: str) -> str:
    normalized = _normalized_row(row)
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


def violation_snapshot_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """Source-table key used to collapse N enforcement rows into one violation snapshot."""
    return (
        _value(row, "SUBMISSIONYEARQUARTER"),
        _value(row, "PWSID"),
        _value(row, "VIOLATION_ID"),
    )


def _enforcement_action(row: dict[str, Any]) -> dict[str, str | None] | None:
    normalized = _normalized_row(row)
    action = {
        field.lower(): (
            str(normalized[field]).strip()
            if normalized.get(field) is not None and str(normalized[field]).strip()
            else None
        )
        for field in sorted(ENFORCEMENT_FIELDS)
    }
    return action if any(value is not None for value in action.values()) else None


def collapse_violation_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Collapse association rows for one SDWIS violation snapshot.

    Violation-level fields must agree.  Enforcement columns are retained as an
    explicit N-cardinality list instead of being misclassified as revisions.
    """
    materialized = list(rows)
    if not materialized:
        raise ValueError("cannot collapse an empty SDWIS violation snapshot")

    normalized_rows = [_normalized_row(row) for row in materialized]
    keys = {violation_snapshot_key(row) for row in normalized_rows}
    if len(keys) != 1:
        raise ValueError(f"mixed SDWIS violation snapshot keys: {sorted(keys)}")

    representative = normalized_rows[0]
    violation_fields = sorted(
        set().union(*(row.keys() for row in normalized_rows)) - ENFORCEMENT_FIELDS
    )
    conflicts: dict[str, list[str]] = {}
    for field in violation_fields:
        values = {
            str(row.get(field) or "").strip()
            for row in normalized_rows
        }
        if len(values) > 1:
            conflicts[field] = sorted(values)
    if conflicts:
        raise ValueError(f"conflicting violation-level values within source snapshot: {conflicts}")

    actions_by_digest: dict[str, dict[str, str | None]] = {}
    for row in normalized_rows:
        action = _enforcement_action(row)
        if action is not None:
            actions_by_digest[row_digest(action)] = action

    collapsed = {
        field: representative.get(field)
        for field in violation_fields
    }
    collapsed["_ENFORCEMENT_ACTIONS"] = [
        actions_by_digest[digest] for digest in sorted(actions_by_digest)
    ]
    collapsed["_SOURCE_ROW_COUNT"] = len(materialized)
    collapsed["_SOURCE_ROW_SHA256S"] = sorted(row_digest(row) for row in normalized_rows)
    return collapsed


def canonical_event_id(row: dict[str, Any]) -> str:
    pwsid = _value(row, "PWSID")
    violation_id = _value(row, "VIOLATION_ID")
    if pwsid and violation_id:
        return f"EPA_SDWIS_VIOLATION:{pwsid}:{violation_id}"
    return f"EPA_SDWIS_VIOLATION_UNRESOLVED:{row_digest(row)[:24]}"


def snapshot_digest(row: dict[str, Any]) -> str:
    """Digest material violation state, independent of quarterly transport metadata."""
    payload: dict[str, Any] = {}
    for key, value in row.items():
        normalized_key = str(key).strip().upper()
        if normalized_key == "SUBMISSIONYEARQUARTER":
            continue
        if normalized_key in _INTERNAL_NONMATERIAL_FIELDS:
            continue
        payload[normalized_key] = value
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def stable_record_id(row: dict[str, Any]) -> str:
    return f"{canonical_event_id(row)}:REV:{snapshot_digest(row)[:20]}"


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
    """Normalize one collapsed SDWIS violation snapshot without inferring exposure."""
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

    enforcement_actions = row.get("_ENFORCEMENT_ACTIONS")
    if not isinstance(enforcement_actions, list):
        enforcement_actions = []

    source_row_hashes = row.get("_SOURCE_ROW_SHA256S")
    if not isinstance(source_row_hashes, list):
        source_row_hashes = [row_digest(row)]

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
            "enforcement_actions": enforcement_actions,
            "source_row_count": int(row.get("_SOURCE_ROW_COUNT") or len(source_row_hashes)),
            "source_row_sha256s": source_row_hashes,
            "violation_snapshot_sha256": snapshot_digest(row),
            "semantic_guardrail": (
                "Compliance/monitoring/public-notification violations do not by themselves "
                "establish contaminant exposure or measured exceedance."
            ),
        },
    )
