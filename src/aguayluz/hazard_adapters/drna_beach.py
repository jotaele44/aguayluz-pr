"""DRNA beach-monitoring adapter for the canonical hazard plane.

The adapter consumes already-parsed official DRNA notification semantics. Acquisition
and HTML parsing stay separate so exact source bytes are frozen before normalization.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus

BAV_ENTEROCOCCI_CFU_PER_100ML = 70
ADVISORY_BAV_EXCEEDANCE = "BAV_EXCEEDANCE_NOT_SUITABLE_FOR_BATHERS"
ADVISORY_OTHER_WATER_QUALITY = "OTHER_WATER_QUALITY_PRIMARY_CONTACT_NOT_RECOMMENDED"
ADVISORY_ALL_CLEAR = "ALL_MONITORED_BEACHES_SUITABLE_FOR_BATHERS"
PR_TZ = timezone(timedelta(hours=-4))


def row_digest(row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().upper())
    return value.strip("_") or "UNRESOLVED"


def canonical_event_id(row: dict[str, Any]) -> str:
    post_id = _slug(str(row.get("post_id") or "UNRESOLVED_POST"))
    advisory_key = _slug(
        str(
            row.get("station_id")
            or row.get("beach_name")
            or row.get("advisory_state")
            or "UNRESOLVED_ADVISORY"
        )
    )
    return f"DRNA_BEACH:{post_id}:{advisory_key}"


def stable_record_id(row: dict[str, Any]) -> str:
    return f"{canonical_event_id(row)}:REV:{row_digest(row)[:20]}"


def _date_start(value: Any) -> datetime | None:
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=PR_TZ)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=PR_TZ)


def normalize(
    row: dict[str, Any],
    manifestation_id: str,
    *,
    supersedes_record_id: str | None = None,
) -> HazardRecord:
    """Normalize one DRNA notification-derived advisory without inventing bindings."""
    advisory_state = str(row.get("advisory_state") or "").strip()
    if advisory_state == ADVISORY_BAV_EXCEEDANCE:
        hazard_type = "BEACH_ENTEROCOCCI_BAV_EXCEEDANCE"
    elif advisory_state == ADVISORY_OTHER_WATER_QUALITY:
        hazard_type = "BEACH_WATER_QUALITY_ADVISORY_OTHER_OBSERVATION"
    elif advisory_state == ADVISORY_ALL_CLEAR:
        hazard_type = "BEACH_MONITORING_ALL_CLEAR"
    else:
        hazard_type = "BEACH_MONITORING_UNRESOLVED"

    published_at = row.get("published_at")
    if isinstance(published_at, str) and published_at:
        try:
            issued_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            issued_at = None
    else:
        issued_at = published_at if isinstance(published_at, datetime) else None

    station_id = str(row.get("station_id") or "").strip() or None
    beach_name = str(row.get("beach_name") or "").strip() or None
    municipality_raw = str(row.get("municipality_raw") or "").strip() or None
    title = str(row.get("title_raw") or "").strip()
    if not title:
        if advisory_state == ADVISORY_ALL_CLEAR:
            title = "DRNA beach monitoring: all monitored beaches suitable for bathers"
        else:
            title = f"DRNA beach advisory: {beach_name or station_id or 'unresolved site'}"

    return HazardRecord(
        record_id=stable_record_id(row),
        canonical_event_id=canonical_event_id(row),
        record_kind=RecordKind.ADVISORY,
        family=HazardFamily.WATER_HEALTH,
        hazard_type=hazard_type,
        source_authority="Puerto Rico DRNA",
        source_record_id=str(row.get("source_record_id") or canonical_event_id(row)),
        manifestation_id=manifestation_id,
        title_raw=title,
        description_raw=str(row.get("description_raw") or "").strip() or None,
        normalized_label=beach_name,
        status=RecordStatus.FINAL if advisory_state else RecordStatus.UNRESOLVED,
        observed_from=_date_start(row.get("sample_date_start")),
        observed_to=_date_start(row.get("sample_date_end")),
        reported_at=issued_at,
        issued_at=issued_at,
        effective_from=issued_at,
        geography_basis=(
            "DRNA_STATION_AND_MUNICIPALITY_TEXT_UNBOUND"
            if station_id or municipality_raw
            else "DRNA_PROGRAM_SCOPE_NO_SITE_ENUMERATION"
        ),
        geometry_precision="NONE_UNLESS_INDEPENDENTLY_BOUND",
        supersedes_record_id=supersedes_record_id,
        raw_attributes={
            "post_id": row.get("post_id"),
            "post_url": row.get("post_url"),
            "station_id": station_id,
            "beach_name": beach_name,
            "municipality_raw": municipality_raw,
            "indicator": row.get("indicator"),
            "bav_value": row.get("bav_value"),
            "bav_unit": row.get("bav_unit"),
            "sample_date_start": row.get("sample_date_start"),
            "sample_date_end": row.get("sample_date_end"),
            "temporal_precision": "DATE_ONLY" if row.get("sample_date_start") else None,
            "advisory_state": advisory_state or None,
            "advisory_reason_raw": row.get("advisory_reason_raw"),
            "source_excerpt": row.get("source_excerpt"),
            "source_row_sha256": row_digest(row),
            "source_row": row,
        },
    )
