"""NWS marine-zone alert adapter for the outdoor-conditions layer.

Input is one feature from ``GET /alerts/active?area=AM`` (the whole western Atlantic
marine area). Only alerts naming a WFO San Juan marine zone (``AMZ7xx``, frozen in
``data/reference/outdoor_reference.v1.json``) are retained.

Identity is the VTEC event — office, phenomenon, significance, event tracking number
and year — not the CAP message id: NWS re-issues a Small Craft Advisory under a new
message id every few hours (``messageType: Update``, VTEC action ``CON``/``EXT``), and
those are revisions of one event. A revision is written only when the material state
(event name, PR zones, end time, VTEC action class) changes. An event that leaves the
active set, or whose VTEC action is ``CAN``/``EXP``, is closed by a ``TERMINATED``
revision. Alerts without VTEC fall back to the CAP id.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus

SOURCE_AUTHORITY = "NOAA/NWS Weather Forecast Office San Juan"
CANONICAL_PREFIX = "NWS_MARINE:"
HAZARD_TYPE = "MARINE_HAZARD_ADVISORY"

_VTEC_RE = re.compile(
    r"/(?P<product>[OTEX])\.(?P<action>[A-Z]{3})\.(?P<office>[A-Z]{4})\.(?P<phen>[A-Z]{2})\."
    r"(?P<sig>[A-Z])\.(?P<etn>\d{4})\.(?P<start>\d{6}T\d{4}Z)-(?P<end>\d{6}T\d{4}Z)/"
)
#: VTEC actions that close an event.
CLOSING_ACTIONS = frozenset({"CAN", "EXP", "UPG"})


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def vtec(props: dict[str, Any]) -> dict[str, str] | None:
    """The first operational VTEC string of an alert, parsed."""
    for raw in (props.get("parameters") or {}).get("VTEC") or []:
        match = _VTEC_RE.search(str(raw))
        if match and match.group("product") == "O":
            return match.groupdict()
    return None


def ugc_zones(props: dict[str, Any]) -> list[str]:
    return [str(z) for z in ((props.get("geocode") or {}).get("UGC") or [])]


def event_key(props: dict[str, Any]) -> str:
    """``TJSJ.SC.Y.0042.2026`` from VTEC, else the CAP message id."""
    parsed = vtec(props)
    if parsed:
        sent = parse_time(props.get("sent"))
        year = sent.astimezone(timezone.utc).year if sent else 0
        return f"{parsed['office']}.{parsed['phen']}.{parsed['sig']}.{parsed['etn']}.{year}"
    return str(props.get("id") or "").strip()


def canonical_event_id(key: str) -> str:
    return f"{CANONICAL_PREFIX}{key}"


def classify(feature: Any, pr_zones: set[str]) -> str:
    """retained | excluded:<reason> | unresolved:<reason> for one alert feature."""
    if not isinstance(feature, dict):
        return "unresolved:not_an_object"
    props = feature.get("properties") or {}
    if not props.get("id"):
        return "unresolved:missing_id"
    if props.get("status") != "Actual":
        return f"excluded:status_{str(props.get('status') or 'blank').lower()}"
    if not set(ugc_zones(props)) & pr_zones:
        return "excluded:outside_pr_marine_zones"
    return "retained"


def material_state(props: dict[str, Any], pr_zones: set[str], *, closed: bool = False) -> dict[str, Any]:
    parsed = vtec(props) or {}
    ends = parse_time(props.get("ends")) or parse_time(props.get("expires"))
    action = parsed.get("action")
    return {
        "event_key": event_key(props),
        "event": props.get("event"),
        "zones": sorted(set(ugc_zones(props)) & pr_zones),
        "ends": ends.astimezone(timezone.utc).isoformat() if ends else None,
        "closed": closed or action in CLOSING_ACTIONS or props.get("messageType") == "Cancel",
    }


def material_digest(material: dict[str, Any]) -> str:
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def stable_record_id(material: dict[str, Any], supersedes_record_id: str | None) -> str:
    chained = sha256(
        f"{material_digest(material)}|{supersedes_record_id or 'HEAD'}".encode()
    ).hexdigest()
    return f"{canonical_event_id(material['event_key'])}:REV:{chained[:20]}"


def normalize(
    props: dict[str, Any],
    pr_zones: set[str],
    manifestation_id: str,
    *,
    supersedes_record_id: str | None = None,
    closed: bool = False,
    closed_at: datetime | None = None,
) -> HazardRecord:
    material = material_state(props, pr_zones, closed=closed)
    parsed = vtec(props) or {}
    effective = parse_time(props.get("onset")) or parse_time(props.get("effective"))
    ends = parse_time(material["ends"]) if material["ends"] else None
    if material["closed"] and closed_at is not None and (ends is None or closed_at < ends):
        ends = closed_at
    if effective and ends and ends < effective:
        ends = effective
    event_name = str(props.get("event") or "Marine alert").strip()
    return HazardRecord(
        record_id=stable_record_id(material, supersedes_record_id),
        canonical_event_id=canonical_event_id(material["event_key"]),
        record_kind=RecordKind.ADVISORY,
        family=HazardFamily.HYDROMETEOROLOGY,
        hazard_type=HAZARD_TYPE,
        source_authority=SOURCE_AUTHORITY,
        source_record_id=str(props.get("id")),
        manifestation_id=manifestation_id,
        title_raw=event_name,
        description_raw=props.get("headline"),
        normalized_label=f"{event_name} — {', '.join(material['zones'])}",
        status=RecordStatus.TERMINATED if material["closed"] else RecordStatus.ACTIVE,
        issued_at=parse_time(props.get("sent")),
        effective_from=effective,
        effective_to=ends,
        geography_basis="NWS_MARINE_ZONE:UGC",
        geometry_precision="REPRESENTATIVE_POINT",
        supersedes_record_id=supersedes_record_id,
        raw_attributes={
            "id": props.get("id"),
            "areaDesc": props.get("areaDesc"),
            "geocode": props.get("geocode"),
            "messageType": props.get("messageType"),
            "severity": props.get("severity"),
            "certainty": props.get("certainty"),
            "urgency": props.get("urgency"),
            "senderName": props.get("senderName"),
            "headline": props.get("headline"),
            "vtec": (props.get("parameters") or {}).get("VTEC"),
            "nws_headline": (props.get("parameters") or {}).get("NWSheadline"),
        },
        normalized_values={
            **material,
            "vtec_action": parsed.get("action"),
            "phenomenon": parsed.get("phen"),
            "significance": parsed.get("sig"),
            "nws_severity": props.get("severity"),
            "material_digest": material_digest(material),
        },
    )


def close_record(head: HazardRecord, manifestation_id: str, closed_at: datetime) -> HazardRecord:
    """A TERMINATED revision of ``head`` for an event that left the active-alert set.

    ``manifestation_id`` is the active-set response that no longer lists the event —
    the evidence for the closure.
    """
    material = {k: head.normalized_values.get(k) for k in ("event_key", "event", "zones", "ends")}
    material["closed"] = True
    ends = head.effective_to
    if ends is None or closed_at < ends:
        ends = closed_at
    if head.effective_from and ends < head.effective_from:
        ends = head.effective_from
    return head.model_copy(update={
        "record_id": stable_record_id(material, head.record_id),
        "manifestation_id": manifestation_id,
        "status": RecordStatus.TERMINATED,
        "effective_to": ends,
        "supersedes_record_id": head.record_id,
        "normalized_values": {**head.normalized_values, **material,
                              "closed_reason": "left_active_set",
                              "material_digest": material_digest(material)},
    })


__all__ = [
    "CANONICAL_PREFIX",
    "CLOSING_ACTIONS",
    "close_record",
    "HAZARD_TYPE",
    "SOURCE_AUTHORITY",
    "canonical_event_id",
    "classify",
    "event_key",
    "material_digest",
    "material_state",
    "normalize",
    "parse_time",
    "stable_record_id",
    "ugc_zones",
    "vtec",
]
