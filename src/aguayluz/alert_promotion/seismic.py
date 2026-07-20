"""Promote ingested USGS earthquake service-events into SEISMIC_GEO AlertEvents.

``scripts/ingest_usgs_quakes.py`` writes each near-real-time USGS FDSN earthquake into
``data/service_events.jsonl`` as a raw ``service_interruption`` row whose ``status_text``
carries the magnitude, depth and place, e.g.::

    earthquake M2.91 depth=18.53 km place='27 km NW of Rincón, Puerto Rico' source='pr'

Until now nothing turned that raw event into an operational alert, so a real quake
never surfaced on the SEISMIC_GEO module (its only row was a blocked dormant seed).
This promoter closes that gap: it parses the magnitude and place and emits a validated
SEISMIC_GEO :class:`~aguayluz.alerts.AlertEvent`, with severity scaled from magnitude so
that a major quake clears the life-safety / push threshold.

Pure functions only (no I/O, no wall-clock). Real T1 USGS data in, real alert out.
"""

from __future__ import annotations

import re
from typing import Any

from ..alerts import AlertEvent
from ..water_alerts import _centroid, _geo_key, _slug

SEISMIC_MARKER = "_seismic_"

#: Only USGS earthquake rows are promoted (identified by their source_ref prefix).
_SEISMIC_SOURCE_PREFIX = "USGS-EQ"

_MAG_RE = re.compile(r"\bM\s*([0-9]+(?:\.[0-9]+)?)")
_PLACE_RE = re.compile(r"place='([^']*)'")


def _magnitude(status_text: str | None) -> float | None:
    m = _MAG_RE.search(status_text or "")
    return float(m.group(1)) if m else None


def _place(status_text: str | None, fallback: str) -> str:
    m = _PLACE_RE.search(status_text or "")
    return (m.group(1) if m else "").strip() or fallback


def _severity_for_magnitude(mag: float) -> int:
    """Map Richter magnitude to the workbook's 0-5 operational severity floor.

    M6+ -> 5 (major), M5-6 -> 4 (critical/push), M4-5 -> 3, M3-4 -> 2, <M3 -> 1.
    """
    if mag >= 6.0:
        return 5
    if mag >= 5.0:
        return 4
    if mag >= 4.0:
        return 3
    if mag >= 3.0:
        return 2
    return 1


def _place_municipality(place: str, geo: dict[str, dict[str, Any]]) -> str | None:
    """Best-effort municipality from a USGS place string ("27 km NW of Rincón, PR").

    Tries the token after " of " first, then any municipio name that appears in the
    place text. Returns the matched municipality's display name, or ``None``.
    """
    cleaned = place.replace(", Puerto Rico", "").replace(", PR", "")
    candidate = cleaned.split(" of ")[-1].strip() if " of " in cleaned else cleaned.strip()
    if candidate and _geo_key(candidate) in geo:
        return geo[_geo_key(candidate)]["name"]
    # fall back to scanning every municipio name against the folded place text
    folded = _geo_key(place)
    for key, rec in geo.items():
        if key and key in folded:
            return rec["name"]
    return None


def seismic_alert(event: dict[str, Any], geo: dict[str, dict[str, Any]]) -> AlertEvent | None:
    """Project one USGS earthquake service-event into a SEISMIC_GEO AlertEvent."""
    if not str(event.get("source_ref", "")).startswith(_SEISMIC_SOURCE_PREFIX):
        return None
    mag = _magnitude(event.get("status_text"))
    if mag is None:
        return None

    place = _place(event.get("status_text"), event.get("affected_area") or "PR region")
    muni = _place_municipality(place, geo)
    munis = [muni] if muni else ["(unscoped)"]
    lat, lon = _centroid(muni, geo) if muni else (None, None)

    severity = _severity_for_magnitude(mag)
    quake_id = str(event.get("source_ref", "")).split(":", 1)[-1] or (event.get("event_id") or place)
    date = "".join(ch for ch in str(event.get("start_time") or "")[:10] if ch.isdigit())[:8] or "00000000"

    return AlertEvent(
        alert_id=f"AYL_ALR_{date}{SEISMIC_MARKER}{_slug(quake_id)}",
        module_id="SEISMIC_GEO",
        event_type="hazard",
        status="active",
        source_title=f"Earthquake M{mag:g} — {place}",
        source_ref=event.get("source_ref") or "USGS-EQ",
        source_hash=event.get("source_hash"),
        published_at=None,
        start_at=event.get("start_time"),
        end_at=None,
        asset_name=place,
        asset_id=None,
        operator="USGS",
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
        validation_notes=f"Derived from USGS FDSN earthquake M{mag:g}; severity scaled from magnitude.",
    )


def seismic_alerts(
    events: list[dict[str, Any]], geo: dict[str, dict[str, Any]]
) -> list[AlertEvent]:
    """Promote every USGS earthquake service-event into a SEISMIC_GEO alert."""
    out: list[AlertEvent] = []
    for ev in events:
        alert = seismic_alert(ev, geo)
        if alert is not None:
            out.append(alert)
    return out
