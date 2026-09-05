"""FDA food enforcement adapter for the canonical hazard plane.

The adapter normalizes already-fetched openFDA rows. Acquisition is deliberately
separate so source bytes and HTTP metadata can be frozen before normalization.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus

PR_EXPLICIT = "CONFIRMED_PR_DISTRIBUTION"
PR_NATIONAL_CANDIDATE = "NATIONAL_DISTRIBUTION_PR_NOT_INDEPENDENTLY_CONFIRMED"
PR_NO_INDICATION = "NO_PR_INDICATION"


def _date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def classify_pr_relevance(row: dict[str, Any]) -> str:
    """Classify distribution evidence without turning nationwide into PR proof."""
    distribution = str(row.get("distribution_pattern") or "")
    normalized = distribution.casefold()
    if "puerto rico" in normalized or re.search(r"(?:^|[\s,;/])pr(?:$|[\s,;/])", normalized):
        return PR_EXPLICIT
    if "nationwide" in normalized or "nation wide" in normalized:
        return PR_NATIONAL_CANDIDATE
    return PR_NO_INDICATION


def stable_record_id(row: dict[str, Any]) -> str:
    recall_number = str(row.get("recall_number") or "").strip()
    if recall_number:
        return f"FDA_FOOD_RECALL:{recall_number}"
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"FDA_FOOD_RECALL_UNRESOLVED:{sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def normalize(row: dict[str, Any], manifestation_id: str) -> HazardRecord:
    """Normalize one openFDA enforcement row without synthetic field aggregation."""
    record_id = stable_record_id(row)
    source_record_id = str(row.get("recall_number") or row.get("event_id") or record_id)
    status_raw = str(row.get("status") or "").casefold()
    if "terminated" in status_raw:
        status = RecordStatus.TERMINATED
    elif status_raw:
        status = RecordStatus.ACTIVE
    else:
        status = RecordStatus.UNRESOLVED

    return HazardRecord(
        record_id=record_id,
        record_kind=RecordKind.ADVISORY,
        family=HazardFamily.FOOD_SAFETY,
        hazard_type="FDA_FOOD_ENFORCEMENT_RECALL",
        source_authority="FDA",
        source_record_id=source_record_id,
        manifestation_id=manifestation_id,
        title_raw=str(row.get("product_description") or "FDA food enforcement recall"),
        description_raw=str(row.get("reason_for_recall") or "") or None,
        normalized_label=str(row.get("classification") or "") or None,
        status=status,
        observed_from=_date(row.get("recall_initiation_date")),
        reported_at=_date(row.get("report_date")),
        effective_to=_date(row.get("termination_date")),
        geography_basis="DISTRIBUTION_PATTERN_TEXT",
        geometry_precision="NONE_UNLESS_INDEPENDENTLY_BOUND",
        raw_attributes={
            "event_id": row.get("event_id"),
            "recall_number": row.get("recall_number"),
            "classification": row.get("classification"),
            "product_description": row.get("product_description"),
            "code_info": row.get("code_info"),
            "product_quantity": row.get("product_quantity"),
            "recalling_firm": row.get("recalling_firm"),
            "firm_city": row.get("city"),
            "firm_state": row.get("state"),
            "firm_country": row.get("country"),
            "distribution_pattern": row.get("distribution_pattern"),
            "pr_relevance": classify_pr_relevance(row),
            "voluntary_mandated": row.get("voluntary_mandated"),
            "initial_firm_notification": row.get("initial_firm_notification"),
            "source_row": row,
        },
    )
