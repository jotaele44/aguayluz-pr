"""Promote NHC tropical-cyclone service-events into WEATHER_HAZARD AlertEvents.

``scripts/ingest_nhc_storms.py`` writes each active Atlantic cyclone in the Puerto Rico
approach corridor into ``data/service_events.jsonl``. Without this promoter those rows
stop at raw service events and never become alerts:
:func:`aguayluz.alert_promotion.weather.weather_alert` keys on the ``event='…'`` marker
that ``ingest_nws_alerts.py`` writes, and returns ``None`` for anything else. So a
hurricane entering the corridor produced a row nothing acted on — which defeats the
reason the NHC feed exists, since its whole value over the NWS feed is lead time.

Why a separate promoter rather than making the ingest emit ``event='…'``:

* **Severity has to be distance-aware.** The NWS promoter reads a *watch or warning*,
  which NWS only issues once PR is inside the forecast envelope, so the hazard name
  alone carries the urgency. NHC publishes every storm from genesis, so classification
  alone does not: a Category 4 six hours out and a Category 4 off Cabo Verde are the same
  string and nowhere near the same alert. This scales by classification **and** distance
  to the island, so only a storm that is both strong and close clears
  :data:`~aguayluz.alert_promotion.CRITICAL_SEVERITY` and reaches push/SMS.
* Squeezing a storm into the NWS ``_HAZARD_SEVERITY`` substring table would make
  "Hurricane Bertha" score identically to a "Hurricane Warning", conflating a forecast
  position with an issued warning.

Pure functions only (no I/O, no wall-clock). Real T1 NHC data in, real alert out.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from ..alerts import AlertEvent
from ..impact import AssetIndex, in_alert_bounds, link_impact, merge_asset_ids
from ..water_alerts import _slug

NHC_MARKER = "_nhc_"

#: Only rows written by ``scripts/ingest_nhc_storms.py`` carry this ``source_ref`` prefix.
_SOURCE_PREFIX = "NHC-"
_STORM_RE = re.compile(r"^NHC-([a-z]{2}\d{6})", re.IGNORECASE)

#: Geographic centre of Puerto Rico, for the storm-distance calculation.
_PR_LAT, _PR_LON = 18.22, -66.40

#: Base operational severity (0-5) by NHC classification code, before distance scaling.
_CLASS_SEVERITY: dict[str, int] = {
    "MH": 4,    # major hurricane (Cat 3+)
    "HU": 4,    # hurricane
    "TY": 4,    # typhoon (not an Atlantic code, mapped for completeness)
    "TS": 3,    # tropical storm
    "STS": 3,   # subtropical storm
    "TD": 2,    # tropical depression
    "STD": 2,   # subtropical depression
    "PTC": 2,   # potential tropical cyclone
    "PC": 1,    # post-tropical cyclone
    "LO": 1,    # low
    "DB": 1,    # disturbance
}

#: Distance thresholds (km) from the island. NHC issues watches around 48 h out, which
#: for a typical 20-25 km/h forward speed is roughly 500 km — hence the escalation band.
_NEAR_KM = 500.0
_FAR_KM = 1000.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Local, so this module stays dependency-free."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def storm_severity(classification: str, distance_km: float | None) -> int:
    """Operational severity 0-5 from NHC classification, scaled by distance to PR.

    A storm that is strong **and** close is the only combination that clears the
    life-safety threshold. A Category 4 still 1,500 km east is a watch item, not a
    push notification, and treating the two alike would train operators to ignore both.
    """
    base = _CLASS_SEVERITY.get(str(classification or "").strip().upper(), 2)
    if distance_km is None:
        return base
    if distance_km <= _NEAR_KM:
        return min(5, base + 1)
    if distance_km > _FAR_KM:
        return max(1, base - 1)
    return base


def _storm_meta(event: dict[str, Any]) -> tuple[str, str, str] | None:
    """``(storm_id, classification_label, storm_name)`` from an NHC service-event row."""
    source_ref = str(event.get("source_ref") or "")
    m = _STORM_RE.match(source_ref)
    if not m:
        return None
    # source_ref is "NHC-<id> <Classification label> <Name>; <advisory url>"
    head = source_ref.split(";", 1)[0]
    rest = head[len(f"{_SOURCE_PREFIX}{m.group(1)}"):].strip()
    if not rest:
        return None
    label, _, name = rest.rpartition(" ")
    return m.group(1), (label.strip() or rest), (name.strip() or rest)


def _class_code(label: str) -> str:
    """Map the human label the ingest writes back to an NHC classification code."""
    lowered = label.lower()
    for code, needle in (
        ("MH", "major hurricane"), ("PTC", "potential tropical cyclone"),
        ("STS", "subtropical storm"), ("STD", "subtropical depression"),
        ("PC", "post-tropical"), ("TD", "tropical depression"),
        ("TS", "tropical storm"), ("HU", "hurricane"), ("TY", "typhoon"),
        ("DB", "disturbance"), ("LO", "low"),
    ):
        if needle in lowered:
            return code
    return ""


def nhc_alert(
    event: dict[str, Any],
    geo: dict[str, dict[str, Any]] | None = None,
    index: AssetIndex | None = None,
) -> AlertEvent | None:
    """Project one NHC cyclone service-event into a WEATHER_HAZARD AlertEvent."""
    del geo  # storm position comes from the event itself; no municipio lookup needed
    index = index or AssetIndex()
    meta = _storm_meta(event)
    if meta is None:      # not an NHC row — NWS/SDWIS/quake rows fall through untouched
        return None
    storm_id, label, name = meta

    lat, lon = event.get("lat"), event.get("lon")
    distance = (
        _haversine_km(float(lat), float(lon), _PR_LAT, _PR_LON)
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float))
        else None
    )
    severity = storm_severity(_class_code(label), distance)

    # A storm still out at sea cannot carry coordinates: alert_event bounds latitude and
    # longitude to Puerto Rico, so an approaching centre at 64W is out of range. Same
    # treatment the seismic promoter gives an offshore epicentre — record it as unknown
    # rather than clamping to a misleading on-land point.
    if in_alert_bounds(lat, lon):
        a_lat: float | None = round(float(lat), 6)   # type: ignore[arg-type]
        a_lon: float | None = round(float(lon), 6)   # type: ignore[arg-type]
        coord_confidence: Literal["exact", "approximate", "unknown"] = "exact"
    else:
        a_lat = a_lon = None
        coord_confidence = "unknown"

    linked, sectors = link_impact(a_lat, a_lon, [], index, radius_km=None)

    start = str(event.get("start_time") or "")
    date = "".join(ch for ch in start[:10] if ch.isdigit())[:8] or "00000000"
    # Anchored on the advisory, matching the service-event id, so re-running the same
    # advisory replaces its alert while successive advisories accumulate into a track.
    advisory = str(event.get("event_id") or "").rpartition("-adv")[2] or "0"

    where = (
        f"{distance:.0f} km from Puerto Rico" if distance is not None
        else "position not reported"
    )
    return AlertEvent(
        alert_id=f"AYL_ALR_{date}{NHC_MARKER}{_slug(storm_id)}_adv{_slug(advisory)}",
        module_id="WEATHER_HAZARD",
        event_type="hazard",
        status="active",
        source_title=f"{label} {name} — {where}",
        source_ref=event.get("source_ref") or "NHC",
        source_hash=event.get("source_hash"),
        published_at=None,
        start_at=str(event.get("start_time") or ""),
        end_at=event.get("end_time"),
        # A cyclone is not infrastructure, but asset_name is a required string — carry the
        # storm's own identity rather than an empty placeholder.
        asset_name=f"{label} {name}",
        asset_id=None,
        operator="NOAA/NHC",
        municipalities=["(unscoped)"],
        sectors_impacted=sectors,
        latitude=a_lat,
        longitude=a_lon,
        coord_confidence=coord_confidence,
        severity=severity,
        confidence=int(event.get("confidence") or 85),
        ilap_score=None,
        covert_flags=[],
        gap_status="none",
        review_status=event.get("review_status") or "accepted",
        evidence_tier=event.get("evidence_tier") or "T1",
        linked_asset_ids=merge_asset_ids(event.get("linked_asset_ids"), linked),
        validation_notes=(
            f"Derived from NHC advisory {advisory} for {storm_id}; severity scaled from "
            f"classification and distance to Puerto Rico ({where}). Forecast position, "
            f"NOT an issued NWS watch or warning — those arrive via ingest_nws_alerts.py."
        ),
    )


def nhc_alerts(
    events: list[dict[str, Any]] | None,
    geo: dict[str, dict[str, Any]] | None = None,
    index: AssetIndex | None = None,
) -> list[AlertEvent]:
    """Promote every NHC cyclone service-event into a WEATHER_HAZARD alert."""
    out: list[AlertEvent] = []
    for ev in events or []:
        alert = nhc_alert(ev, geo, index)
        if alert is not None:
            out.append(alert)
    return out
