"""EPA SDWIS adapter for the canonical Puerto Rico hazard/advisory plane.

SDWIS violations are regulatory events. They are not, by themselves, boil-water,
do-not-drink, do-not-use, contamination-pathway, or exposure advisories. Those
advisory semantics require an explicit authoritative advisory manifestation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus

MICROBIAL_RULE_GROUPS = {"100", "110", "111", "120", "130", "140"}


def row_digest(row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _identity(row: dict[str, Any]) -> tuple[str, str]:
    pwsid = str(row.get("pwsid") or "").strip().upper()
    violation_id = str(row.get("violation_id") or "").strip()
    if not pwsid or not violation_id:
        raise ValueError("SDWIS rows require pwsid and violation_id for canonical identity")
    return pwsid, violation_id


def canonical_event_id(row: dict[str, Any]) -> str:
    pwsid, violation_id = _identity(row)
    return f"EPA_SDWIS:{pwsid}:{violation_id}"


def stable_record_id(row: dict[str, Any]) -> str:
    return f"{canonical_event_id(row)}:REV:{row_digest(row)[:20]}"


def _date_start(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text or text.casefold() == "null":
        return None
    text = text.split("T", 1)[0].split(" ", 1)[0]
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _hazard_type(row: dict[str, Any]) -> str:
    health_based = str(row.get("is_health_based_ind") or "").strip().upper() == "Y"
    category = str(row.get("violation_category_code") or "").strip().upper()
    rule_group = str(row.get("rule_group_code") or "").strip()

    if health_based and rule_group in MICROBIAL_RULE_GROUPS:
        return "SDWA_MICROBIAL_HEALTH_BASED_VIOLATION"
    if health_based:
        return "SDWA_HEALTH_BASED_VIOLATION"
    if category in {"MR", "MON", "MONITORING", "REPORTING"}:
        return "SDWA_MONITORING_REPORTING_VIOLATION"
    if category in {"PN", "PUBLIC NOTICE", "PUBLIC_NOTIFICATION"}:
        return "SDWA_PUBLIC_NOTIFICATION_VIOLATION"
    return "SDWA_REGULATORY_VIOLATION"


def _status(row: dict[str, Any]) -> RecordStatus:
    code = str(row.get("compliance_status_code") or "").strip().upper()
    if code == "R":
        return RecordStatus.TERMINATED
    if code in {"O", "OPEN"}:
        return RecordStatus.ACTIVE
    return RecordStatus.UNRESOLVED


def normalize(
    row: dict[str, Any],
    manifestation_id: str,
    *,
    supersedes_record_id: str | None = None,
) -> HazardRecord:
    """Normalize one authoritative SDWIS violation row without inventing an advisory."""
    pwsid, violation_id = _identity(row)
    hazard_type = _hazard_type(row)
    begin = _date_start(row.get("compl_per_begin_date"))
    end = _date_start(row.get("compl_per_end_date"))
    contaminant = str(row.get("contaminant_code") or "").strip() or "unresolved contaminant"

    return HazardRecord(
        record_id=stable_record_id(row),
        canonical_event_id=canonical_event_id(row),
        record_kind=RecordKind.EVENT,
        family=HazardFamily.WATER_HEALTH,
        hazard_type=hazard_type,
        source_authority="U.S. EPA",
        source_record_id=f"{pwsid}:{violation_id}",
        manifestation_id=manifestation_id,
        title_raw=f"SDWIS violation {violation_id} for public water system {pwsid}",
        description_raw=(
            f"EPA SDWIS violation category={row.get('violation_category_code')} "
            f"code={row.get('violation_code')} contaminant={contaminant}"
        ),
        normalized_label=hazard_type.replace("_", " ").title(),
        status=_status(row),
        observed_from=begin,
        observed_to=end,
        effective_from=begin,
        effective_to=end,
        water_system_id=pwsid,
        geography_basis="EPA_SDWIS_PWSID_AUTHORITATIVE_ID_ONLY",
        geometry_precision="WATER_SYSTEM_ID_ONLY",
        supersedes_record_id=supersedes_record_id,
        raw_attributes={
            "pwsid": pwsid,
            "violation_id": violation_id,
            "population_served_count": row.get("population_served_count"),
            "pws_type_code": row.get("pws_type_code"),
            "violation_code": row.get("violation_code"),
            "violation_category_code": row.get("violation_category_code"),
            "is_health_based_ind": row.get("is_health_based_ind"),
            "contaminant_code": row.get("contaminant_code"),
            "compliance_status_code": row.get("compliance_status_code"),
            "public_notification_tier": row.get("public_notification_tier"),
            "rule_group_code": row.get("rule_group_code"),
            "rule_family_code": row.get("rule_family_code"),
            "primacy_agency_code": row.get("primacy_agency_code"),
            "epa_region": row.get("epa_region"),
            "temporal_precision": "DATE_ONLY",
            "boil_water_advisory_evidence": "NOT_ESTABLISHED_BY_SDWIS_VIOLATION_ALONE",
            "exposure_evidence": "NOT_ESTABLISHED_BY_SDWIS_VIOLATION_ALONE",
            "source_row_sha256": row_digest(row),
            "source_row": row,
        },
    )
