"""NWPS river-gauge adapter for the NWS hydromet plane.

Input is one entry from ``GET /nwps/v1/gauges`` (current observed status) plus the
compact detail from ``GET /nwps/v1/gauges/{lid}`` (thresholds, usgsId, county). The
ingest freezes both responses before calling :func:`normalize`.

A revision is a change of *material state* — flood category, published thresholds,
service state or the USGS site number. Stage values move every 15 minutes and are kept
in the per-gauge state file, not as revisions. The record id hashes the material state
together with the revision it supersedes, so a gauge that floods and recedes twice gets
four distinct revisions instead of collapsing onto the first two.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus

SOURCE_AUTHORITY = "NOAA/NWS National Water Prediction Service"
CANONICAL_PREFIX = "NWPS_GAUGE:"
HAZARD_TYPE = "RIVER_STAGE_FLOOD_CATEGORY"

#: NWS flood categories in rising order. Only these open a flood episode.
FLOOD_CATEGORIES: tuple[str, ...] = ("action", "minor", "moderate", "major")
#: Categories that mean "observed, not in flood" — they close an open episode.
NON_FLOOD_CATEGORIES: tuple[str, ...] = ("no_flooding", "low_threshold", "not_defined")
#: The observation is missing or old; neither opens nor closes an episode.
STALE_CATEGORIES: tuple[str, ...] = ("obs_not_current",)

#: NWPS encodes "no value" as these sentinels.
_MISSING = {-999, -9999, -999.0, -9999.0}


def clean_number(value: Any) -> float | None:
    """A published number, or None for NWPS's -999/-9999 sentinels and non-numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value in _MISSING:
        return None
    return float(value)


def parse_time(value: Any) -> datetime | None:
    """NWPS ISO timestamps; the 0001-01-01 placeholder means "never"."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.year < 1900:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def compact_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
    """The detail fields the plane uses. The full response stays in the snapshot."""
    detail = detail or {}
    flood = detail.get("flood") or {}
    return {
        "lid": detail.get("lid"),
        "usgsId": detail.get("usgsId") or None,
        "reachId": detail.get("reachId") or None,
        "county": detail.get("county") or None,
        "inService": detail.get("inService"),
        "stageUnits": flood.get("stageUnits"),
        "flowUnits": flood.get("flowUnits"),
        "categories": flood.get("categories") or {},
    }


def flood_thresholds(detail: dict[str, Any] | None) -> dict[str, dict[str, float | None]]:
    """Published action/minor/moderate/major thresholds; undefined ones are omitted."""
    categories = (detail or {}).get("categories") or {}
    out: dict[str, dict[str, float | None]] = {}
    for name in FLOOD_CATEGORIES:
        entry = categories.get(name) or {}
        stage, flow = clean_number(entry.get("stage")), clean_number(entry.get("flow"))
        if stage is not None or flow is not None:
            out[name] = {"stage": stage, "flow": flow}
    return out


def in_service(detail: dict[str, Any] | None) -> bool | None:
    state = (detail or {}).get("inService")
    if isinstance(state, dict) and isinstance(state.get("enabled"), bool):
        return state["enabled"]
    return None


def observed_category(entry: dict[str, Any]) -> str:
    observed = ((entry.get("status") or {}).get("observed")) or {}
    return str(observed.get("floodCategory") or "").strip().lower()


def material_state(entry: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "lid": str(entry.get("lid") or "").upper(),
        "flood_category": observed_category(entry),
        "thresholds": flood_thresholds(detail),
        "in_service": in_service(detail),
        "usgs_id": (detail or {}).get("usgsId") or None,
    }


def material_digest(material: dict[str, Any]) -> str:
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def canonical_event_id(lid: str) -> str:
    return f"{CANONICAL_PREFIX}{str(lid).upper()}"


def stable_record_id(material: dict[str, Any], supersedes_record_id: str | None) -> str:
    chained = sha256(
        f"{material_digest(material)}|{supersedes_record_id or 'HEAD'}".encode()
    ).hexdigest()
    return f"{canonical_event_id(material['lid'])}:REV:{chained[:20]}"


def _status(category: str, service: bool | None) -> RecordStatus:
    if service is False:
        return RecordStatus.INACTIVE
    if category in FLOOD_CATEGORIES or category in NON_FLOOD_CATEGORIES:
        return RecordStatus.PROVISIONAL
    if category in STALE_CATEGORIES:
        return RecordStatus.PROVISIONAL
    return RecordStatus.UNRESOLVED


def normalize(
    entry: dict[str, Any],
    detail: dict[str, Any] | None,
    manifestation_id: str,
    *,
    municipality_id: str | None = None,
    geography_basis: str | None = None,
    facility_id: str | None = None,
    supersedes_record_id: str | None = None,
) -> HazardRecord:
    """Normalize one gauge's current status into a HYDROMETEOROLOGY observation."""
    material = material_state(entry, detail)
    observed = ((entry.get("status") or {}).get("observed")) or {}
    name = str(entry.get("name") or "").strip() or material["lid"]
    valid_time = parse_time(observed.get("validTime"))
    return HazardRecord(
        record_id=stable_record_id(material, supersedes_record_id),
        canonical_event_id=canonical_event_id(material["lid"]),
        record_kind=RecordKind.OBSERVATION,
        family=HazardFamily.HYDROMETEOROLOGY,
        hazard_type=HAZARD_TYPE,
        source_authority=SOURCE_AUTHORITY,
        source_record_id=material["lid"],
        manifestation_id=manifestation_id,
        title_raw=name,
        normalized_label=f"{name} ({material['lid']})",
        status=_status(material["flood_category"], material["in_service"]),
        observed_from=valid_time,
        observed_to=valid_time,
        municipality_id=municipality_id,
        facility_id=facility_id,
        geography_basis=geography_basis or "NWPS_GAUGE_POINT_UNBOUND",
        geometry_precision="OBSERVED_POINT",
        provisional=True,
        supersedes_record_id=supersedes_record_id,
        raw_attributes={"gauge": entry, "detail": compact_detail(detail)},
        normalized_values={
            "flood_category": material["flood_category"],
            "observed_stage": clean_number(observed.get("primary")),
            "stage_unit": observed.get("primaryUnit") or None,
            "observed_flow": clean_number(observed.get("secondary")),
            "flow_unit": observed.get("secondaryUnit") or None,
            "valid_time": valid_time.isoformat() if valid_time else None,
            "thresholds": material["thresholds"],
            "in_service": material["in_service"],
            "usgs_id": material["usgs_id"],
            "reach_id": (detail or {}).get("reachId") or None,
            "material_digest": material_digest(material),
        },
    )
