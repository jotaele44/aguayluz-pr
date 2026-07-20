"""Promote ingested NWS hazard service-events into WEATHER_HAZARD AlertEvents.

``scripts/ingest_nws_alerts.py`` writes each active NWS alert for Puerto Rico into
``data/service_events.jsonl`` as a raw row whose ``status_text`` carries the NWS event
name and severity, e.g.::

    event='Heat Advisory' severity=Moderate sender='NWS San Juan PR'
    event='Hurricane Warning' severity=Extreme sender='NWS San Juan PR'

Until now nothing turned these near-real-time hazard events into operational alerts —
WEATHER_HAZARD held only a hand-authored seed — so a live hurricane or flash-flood
warning never surfaced as an actual alert. This promoter parses the NWS event name and
severity and emits a validated WEATHER_HAZARD :class:`~aguayluz.alerts.AlertEvent`, with
severity scaled so hurricane / tsunami / tornado warnings clear the life-safety / push
threshold.

Pure functions only (no I/O, no wall-clock). Real T1 NWS data in, real alert out.
"""

from __future__ import annotations

import re
from typing import Any

from ..alerts import AlertEvent
from ..water_alerts import _centroid, _geo_key, _slug

WEATHER_MARKER = "_weather_"

_EVENT_RE = re.compile(r"event='([^']*)'")
_SEVERITY_RE = re.compile(r"severity=(\w+)")

# NWS hazard name (lowercased) -> base operational severity (0-5). "warning" is the
# actionable tier; "watch"/"advisory" sit a notch lower. Ordered most-severe first;
# the first substring that matches wins.
_HAZARD_SEVERITY: tuple[tuple[str, int], ...] = (
    ("tsunami warning", 5),
    ("tornado warning", 5),
    ("hurricane warning", 5),
    ("extreme wind warning", 5),
    ("tsunami", 4),
    ("hurricane", 4),  # hurricane watch
    ("tropical storm warning", 4),
    ("storm surge warning", 4),
    ("flash flood warning", 4),
    ("tornado", 4),
    ("tropical storm", 3),
    ("storm surge", 3),
    ("coastal flood warning", 3),
    ("flood warning", 3),
    ("excessive heat warning", 3),
    ("high wind warning", 3),
    ("flash flood", 3),
    ("flood", 2),
    ("coastal flood", 2),
    ("heat", 2),
    ("wind", 2),
)


def _base_severity(event_name: str) -> int:
    name = event_name.lower()
    for needle, sev in _HAZARD_SEVERITY:
        if needle in name:
            return sev
    return 2  # unknown hazard: default moderate


def _apply_nws_severity(base: int, token: str | None) -> int:
    """Modulate the base severity by the NWS urgency token (Extreme/Severe/Minor)."""
    tok = (token or "").lower()
    if tok == "extreme":
        return min(5, max(base, 4))
    if tok == "minor" and base > 1:
        return base - 1
    return base


def _areas(event: dict[str, Any]) -> list[str]:
    area = event.get("affected_area") or ""
    parts = [p.strip() for p in str(area).split(";") if p.strip()]
    return parts or ["Puerto Rico"]


def weather_alert(event: dict[str, Any], geo: dict[str, dict[str, Any]]) -> AlertEvent | None:
    """Project one NWS hazard service-event into a WEATHER_HAZARD AlertEvent."""
    status_text = event.get("status_text") or ""
    m = _EVENT_RE.search(status_text)
    if not m:  # only NWS rows carry event='…'; SDWIS/quake rows do not
        return None
    event_name = m.group(1).strip()
    if not event_name:
        return None

    sev_token = _SEVERITY_RE.search(status_text)
    severity = _apply_nws_severity(_base_severity(event_name), sev_token.group(1) if sev_token else None)

    areas = _areas(event)
    # Best-effort coordinates: use a municipio centroid only if the first area names one.
    muni = geo[_geo_key(areas[0])]["name"] if _geo_key(areas[0]) in geo else None
    lat, lon = _centroid(muni, geo) if muni else (None, None)
    munis = [muni] if muni else ["(unscoped)"]

    date = "".join(ch for ch in str(event.get("start_time") or "")[:10] if ch.isdigit())[:8] or "00000000"
    uniq = event.get("event_id") or event.get("source_ref") or event_name

    return AlertEvent(
        alert_id=f"AYL_ALR_{date}{WEATHER_MARKER}{_slug(uniq)}",
        module_id="WEATHER_HAZARD",
        event_type="hazard",
        status="active",
        source_title=f"{event_name} — {areas[0]}",
        source_ref=event.get("source_ref") or "NWS",
        source_hash=event.get("source_hash"),
        published_at=None,
        start_at=event.get("start_time"),
        end_at=event.get("end_time"),
        asset_name=areas[0],
        asset_id=None,
        operator="NWS San Juan",
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
        validation_notes=f"Derived from NWS active alert '{event_name}'; severity scaled from hazard type + NWS urgency.",
    )


def weather_alerts(
    events: list[dict[str, Any]], geo: dict[str, dict[str, Any]]
) -> list[AlertEvent]:
    """Promote every NWS hazard service-event into a WEATHER_HAZARD alert."""
    out: list[AlertEvent] = []
    for ev in events:
        alert = weather_alert(ev, geo)
        if alert is not None:
            out.append(alert)
    return out
