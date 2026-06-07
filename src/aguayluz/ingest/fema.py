"""FEMA OpenFEMA Public Assistance adapter.

Public source: https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails
- No API key required.
- OData-style query: `?$filter=stateAbbreviation eq 'PR' and damageCategoryCode eq 'F'`
- Returns `{metadata: {...}, PublicAssistanceFundedProjectsDetails: [...]}` envelope.

We parse Public Assistance projects and emit `ServiceEvent` records (NOT
`utility_asset` — these are operational events affecting infrastructure, not
the infrastructure itself). Damage categories that aren't utility-relevant
(debris removal, parks) get `is_utility=False` and are skipped by the pipeline.

Utility-relevant damage category codes per FEMA:
  - D: Water Control Facilities → event_type "service_interruption"
  - F: Utilities                → event_type "service_interruption"

All FEMA PA records are evidence_tier T2 (operational/institutional records).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..models import EventType

FEMA_PA_BASE = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
FEMA_PROVENANCE = "FEMA OpenFEMA PublicAssistanceFundedProjectsDetails"

# Damage categories that correspond to utility infrastructure.
UTILITY_DAMAGE_CODES = {"D", "F"}


@dataclass(frozen=True)
class EventSeed:
    """Normalized event-seed produced by a FEMA-like adapter."""

    seed_id: str                          # stable ID, becomes event_id
    event_type: EventType
    affected_area: str
    start_time: str | None = None         # ISO datetime
    end_time: str | None = None
    reported_customers_or_users: int | None = None
    source_ref: str = ""
    source_hash: str | None = None
    notes: str | None = None
    is_utility: bool = True


def _normalize_iso(value: Any) -> str | None:
    """FEMA dates come in as `2017-09-20T00:00:00.000Z` — coerce to a Z-suffix shape."""
    if not value or not isinstance(value, str):
        return None
    # The shape already matches `format: date-time`; just trim sub-second precision
    # so consumers don't need to fish for the variant.
    if value.endswith("Z"):
        # Strip millis to keep canonical Z-suffix.
        if "." in value:
            return value.split(".")[0] + "Z"
        return value
    return value  # let downstream validation reject malformed shapes


def _make_event_id(disaster_number: int | str, gm_project_id: int | str, declaration_date: str | None) -> str:
    """AYL_EVT_<YYYYMMDD>_<slug>; pattern matches the schema."""
    if declaration_date and len(declaration_date) >= 10:
        ymd = declaration_date[:10].replace("-", "")
    else:
        ymd = "00000000"
    slug = f"fema_{disaster_number}_pw{gm_project_id}"
    return f"AYL_EVT_{ymd}_{slug}"


def parse_fema_response(response: dict[str, Any]) -> list[EventSeed]:
    """Parse a FEMA PublicAssistance envelope into EventSeeds."""
    records = response.get("PublicAssistanceFundedProjectsDetails", []) or []
    seeds: list[EventSeed] = []
    for r in records:
        damage_code = (r.get("damageCategoryCode") or "").strip().upper()
        is_utility = damage_code in UTILITY_DAMAGE_CODES

        disaster_number = r.get("disasterNumber") or 0
        gm_project_id = r.get("gmProjectId") or 0
        declaration_date = r.get("declarationDate")
        event_id = _make_event_id(disaster_number, gm_project_id, declaration_date)

        # FEMA gives an upstream `hash` — use it as source_hash when present,
        # otherwise hash the canonical query URL.
        upstream_hash = r.get("hash")
        if upstream_hash and isinstance(upstream_hash, str) and len(upstream_hash) == 40:
            source_hash = upstream_hash
        else:
            url = f"{FEMA_PA_BASE}?$filter=gmProjectId eq {gm_project_id}"
            source_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()

        source_ref = f"{FEMA_PA_BASE}?$filter=gmProjectId eq {gm_project_id}"
        county = (r.get("county") or "").strip() or "Unknown"
        damage_descrip = (r.get("damageCategoryDescrip") or "").strip()
        affected_area = f"{county}, PR — {damage_descrip}" if damage_descrip else f"{county}, PR"

        title = (r.get("applicationTitle") or "").strip()
        process_step = (r.get("projectProcessStep") or "").strip()
        notes_parts: list[str] = []
        if title:
            notes_parts.append(f"title={title}")
        if process_step:
            notes_parts.append(f"step={process_step}")
        if r.get("incidentType"):
            notes_parts.append(f"incident={r['incidentType']}")
        notes = " | ".join(notes_parts) or None

        seeds.append(
            EventSeed(
                seed_id=event_id,
                event_type="project_update",
                affected_area=affected_area,
                start_time=_normalize_iso(r.get("firstObligationDate") or declaration_date),
                end_time=_normalize_iso(r.get("lastObligationDate")),
                reported_customers_or_users=None,
                source_ref=source_ref,
                source_hash=source_hash,
                notes=notes,
                is_utility=is_utility,
            )
        )
    return seeds
