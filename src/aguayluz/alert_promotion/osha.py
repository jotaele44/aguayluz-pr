"""Promote ingested OSHA enforcement service-events into INDUSTRIAL AlertEvents.

``scripts/ingest_osha.py`` writes each PR OSHA inspection into
``data/service_events.jsonl`` as an ``unknown`` service_event whose ``status_text``
carries the establishment, inspection type, NAICS and activity number, e.g.::

    osha inspection activity_nr=317405066 estab='ACME MFG' insp_type='Fatality/Catastrophe' naics=331110 city='Bayamón'

The INDUSTRIAL module (Industrial / Port / Facility Alerts) shipped dormant with no
generator, so an OSHA inspection never became an operational alert. This promoter
closes that gap: it parses the inspection type and emits a validated INDUSTRIAL
:class:`~aguayluz.alerts.AlertEvent`, with severity scaled so a fatality/catastrophe
inspection clears the life-safety / push threshold (severity >= 4).

Pure functions only (no I/O, no wall-clock). Real T1 OSHA data in, real alert out.
"""

from __future__ import annotations

import re
from typing import Any

from ..alerts import AlertEvent
from ..water_alerts import _centroid, _geo_key, _slug

OSHA_MARKER = "_osha_"

#: Only OSHA enforcement rows are promoted (identified by their source_ref prefix).
_OSHA_SOURCE_PREFIX = "OSHA ENFORCEMENT"

_INSP_TYPE_RE = re.compile(r"insp_type='([^']*)'")
_ESTAB_RE = re.compile(r"estab='([^']*)'")
_CITY_RE = re.compile(r"city='([^']*)'")
_ACTIVITY_RE = re.compile(r"activity_nr=(\S+)")


def _field(pattern: re.Pattern[str], text: str | None) -> str:
    m = pattern.search(text or "")
    return (m.group(1) if m else "").strip()


# OSHA IMIS inspection-type codes (the live DOL v4 `insp_type` field is a single
# letter, not a label). See the OSHA enforcement data dictionary.
_INSP_TYPE_LABELS: dict[str, str] = {
    "A": "Accident",
    "B": "Complaint",
    "C": "Referral",
    "D": "Monitoring",
    "E": "Variance",
    "F": "Follow-up",
    "G": "Unprogrammed related",
    "H": "Planned",
    "I": "Programmed related",
    "J": "Unprogrammed other",
    "K": "Other",
    "L": "Programmed other",
    "M": "Fatality/Catastrophe",
}
#: Fatality/catastrophe inspection code — life-safety (severity 5).
_FATALITY_CODES = {"M"}
#: Accident inspection code — reactive to an injury (severity 4).
_ACCIDENT_CODES = {"A"}
#: Reactive (complaint/referral/unprogrammed) inspection codes — elevated.
_REACTIVE_CODES = {"B", "C", "G", "J"}


def _insp_label(insp_type: str) -> str:
    """Human label for an inspection type — decodes a single-letter IMIS code."""
    code = insp_type.strip().upper()
    if len(code) == 1 and code in _INSP_TYPE_LABELS:
        return _INSP_TYPE_LABELS[code]
    return insp_type


def _classify(insp_type: str) -> tuple[str, int]:
    """Map an OSHA inspection type to (AlertEvent event_type, 0-5 severity).

    Handles both the live single-letter IMIS codes and descriptive text labels.
    Fatality/catastrophe and imminent-danger inspections are life-safety hazards
    (severity 5); accident inspections are severe (4, still push-eligible);
    complaint/referral/unprogrammed inspections are elevated (3); programmed and
    other inspections sit at the INDUSTRIAL module's default floor (2).
    """
    t = insp_type.lower()
    raw = insp_type.strip().upper()
    code = raw if len(raw) == 1 else ""  # single-letter IMIS code, else a text label
    if "fatal" in t or "catastrophe" in t or "imminent" in t or code in _FATALITY_CODES:
        return "hazard", 5
    if code in _ACCIDENT_CODES or "accident" in t:
        return "hazard", 4
    if code in _REACTIVE_CODES or "complaint" in t or "referral" in t:
        return "inspection", 3
    return "inspection", 2


def _municipality(city: str, geo: dict[str, dict[str, Any]]) -> str | None:
    """Resolve an OSHA site city to a canonical PR municipio name, best-effort."""
    if city and _geo_key(city) in geo:
        return geo[_geo_key(city)]["name"]
    folded = _geo_key(city)
    for key, rec in geo.items():
        if key and folded and key in folded:
            return rec["name"]
    return None


def osha_alert(event: dict[str, Any], geo: dict[str, dict[str, Any]]) -> AlertEvent | None:
    """Project one OSHA enforcement service-event into an INDUSTRIAL AlertEvent."""
    if not str(event.get("source_ref", "")).startswith(_OSHA_SOURCE_PREFIX):
        return None

    status = event.get("status_text")
    insp_type = _field(_INSP_TYPE_RE, status) or "Unknown"
    estab = _field(_ESTAB_RE, status) or (event.get("affected_area") or "PR establishment")
    city = _field(_CITY_RE, status) or (event.get("municipality") or "")
    activity_nr = _field(_ACTIVITY_RE, status) or (event.get("event_id") or estab)

    event_type, severity = _classify(insp_type)

    # Closure state (from the service_event's end_time): a closed inspection is a
    # historical record, not a current hazard, so it becomes a `closed` alert —
    # which is_critical() excludes from push/SMS regardless of its severity.
    close_at = event.get("end_time")
    status = "closed" if close_at else "active"

    muni = event.get("municipality") or _municipality(city, geo)
    munis = [muni] if muni else ["(unscoped)"]
    lat, lon = _centroid(muni, geo) if muni else (None, None)

    date = "".join(ch for ch in str(event.get("start_time") or "")[:10] if ch.isdigit())[:8] or "00000000"

    return AlertEvent(
        alert_id=f"AYL_ALR_{date}{OSHA_MARKER}{_slug(activity_nr)}",
        module_id="INDUSTRIAL",
        event_type=event_type,
        status=status,
        source_title=f"OSHA {_insp_label(insp_type)} — {estab}",
        source_ref=event.get("source_ref") or _OSHA_SOURCE_PREFIX,
        source_hash=event.get("source_hash"),
        published_at=None,
        start_at=event.get("start_time"),
        end_at=close_at,
        asset_name=estab,
        asset_id=None,
        operator="OSHA",
        municipalities=munis,
        sectors_impacted=[],
        latitude=lat if isinstance(lat, (int, float)) else None,
        longitude=lon if isinstance(lon, (int, float)) else None,
        coord_confidence="approximate" if isinstance(lat, (int, float)) else "unknown",
        severity=severity,
        confidence=int(event.get("confidence") or 85),
        ilap_score=None,
        covert_flags=[],
        gap_status="none",
        review_status=event.get("review_status") or "accepted",
        evidence_tier=event.get("evidence_tier") or "T1",
        linked_asset_ids=list(event.get("linked_asset_ids") or []),
        validation_notes=f"Derived from OSHA inspection ({insp_type}); severity scaled from inspection type.",
    )


def osha_alerts(
    events: list[dict[str, Any]], geo: dict[str, dict[str, Any]]
) -> list[AlertEvent]:
    """Promote every OSHA enforcement service-event into an INDUSTRIAL alert."""
    out: list[AlertEvent] = []
    for ev in events:
        alert = osha_alert(ev, geo)
        if alert is not None:
            out.append(alert)
    return out
