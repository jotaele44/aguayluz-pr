"""Promote outdoor-condition records into WEATHER_HAZARD AlertEvents.

Only **official NWS products** promote; UV, gridded heat index, buoys and AQI are shown
as conditions in ``data/outdoor_conditions.jsonl`` but raise nothing here (an NWS Heat
Advisory already arrives through ``scripts/ingest_nws_alerts.py``).

Rip current (NWS Surf Zone Forecast)
    One alert per zone-day whose *current* forecast revision says rip current risk
    **High**. Severity 3: life-threatening rip currents are likely in the surf zone, but
    the alert stays below the critical push/SMS floor (4) — it is a beach-day hazard,
    not an infrastructure emergency. Active through the forecast day, then ``closed``
    and reported for CLOSED_RETENTION. A later revision that lowers the risk withdraws
    the alert on the next build.

Marine (NWS marine-zone alerts for Puerto Rico waters)
    One alert per VTEC event. Severity 2 for advisories and watches (``Y``/``A``), 3 for
    warnings (``W``); capped at 3, because tropical-cyclone and storm warnings reach the
    critical path through the NHC and land-zone NWS promoters already. ``municipalities``
    are the coastal municipios of the alert's zones (PROXIMITY, within 2 km); an alert
    for offshore zones only names the zones instead.

Pure functions: no I/O. Inputs are the hydromet records (:class:`HydrometInputs`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from ..alerts import AlertEvent
from ..hazard_adapters import nws_marine, nws_surf_zone
from ..hazard_plane import HazardRecord, RecordStatus
from ..hydromet.store import current_by_event
from ..impact import AssetIndex, link_impact, merge_asset_ids
from ..water_alerts import _centroid, _slug
from .hydromet import HydrometInputs

RIP_CURRENT_MARKER = "_ripcurrent_"
MARINE_MARKER = "_marine_"

RIP_CURRENT_SEVERITY = 3
#: Marine severity by VTEC significance; capped below the critical floor.
MARINE_SEVERITY: dict[str, int] = {"Y": 2, "A": 2, "S": 2, "W": 3}
CLOSED_RETENTION = timedelta(days=7)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _place(municipios: list[str], geo: dict[str, dict[str, Any]]) -> tuple[float | None, float | None]:
    """Centroid of the first municipio (approximate) — the alert covers a coastline."""
    for name in municipios:
        lat, lon = _centroid(name, geo)
        if lat is not None:
            return lat, lon
    return None, None


def rip_current_alert(record: HazardRecord, geo: dict[str, dict[str, Any]], index: AssetIndex,
                      now: datetime | None) -> AlertEvent:
    values = record.normalized_values
    zone = str(values.get("zone"))
    day = str(values.get("date"))
    municipios = list(values.get("municipios") or []) or [record.raw_attributes.get("zone_name") or zone]
    lat, lon = _place(municipios, geo)
    closed = now is not None and record.effective_to is not None and now >= record.effective_to
    linked, sectors = link_impact(None, None, municipios, index, radius_km=None)
    lo, hi = values.get("surf_min_ft"), values.get("surf_max_ft")
    surf = f"; surf {lo:g}–{hi:g} ft" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo != hi \
        else (f"; surf around {hi:g} ft" if isinstance(hi, (int, float)) else "")
    product = str(record.source_record_id).split(":", 1)[0]
    notes = [
        f"NWS San Juan Surf Zone Forecast, zone {zone} ({record.raw_attributes.get('zone_name')}), "
        f"{day} ({record.raw_attributes.get('period_label')}): rip current risk High{surf}.",
        "High risk: life-threatening rip currents are likely in the surf zone (NWS category).",
        "Beaches named by the product: " + ", ".join(record.raw_attributes.get("beaches") or municipios) + ".",
        "Municipio binding: AUTHORITATIVE_BINDING (the product's own beach list).",
    ]
    return AlertEvent(
        alert_id=f"AYL_ALR_{day.replace('-', '')}{RIP_CURRENT_MARKER}{zone.lower()}",
        module_id="WEATHER_HAZARD",
        event_type="hazard",
        status="closed" if closed else "active",
        source_title=f"High rip current risk — {record.raw_attributes.get('zone_name') or zone} ({day})",
        source_ref=f"NWS-SRF TJSJ {product}; https://api.weather.gov/products/{product}",
        source_hash=None,
        published_at=_utc(record.issued_at) if record.issued_at else None,
        start_at=_utc(record.effective_from) if record.effective_from else f"{day}T04:00:00Z",
        end_at=_utc(record.effective_to) if closed and record.effective_to else None,
        asset_name=", ".join(municipios),
        asset_id=None,
        operator="NOAA/NWS WFO San Juan",
        municipalities=municipios,
        sectors_impacted=sectors,
        latitude=lat,
        longitude=lon,
        coord_confidence="approximate" if lat is not None else "unknown",
        severity=RIP_CURRENT_SEVERITY,
        confidence=80,
        ilap_score=None,
        covert_flags=[],
        gap_status="none",
        review_status="accepted",
        evidence_tier="T1",
        linked_asset_ids=merge_asset_ids([], linked),
        validation_notes=" ".join(notes),
    )


def rip_current_alerts(inputs: HydrometInputs | None, geo: dict[str, dict[str, Any]] | None = None,
                       index: AssetIndex | None = None) -> list[AlertEvent]:
    if inputs is None:
        return []
    geo, index = geo or {}, index or AssetIndex()
    out = []
    for record in current_by_event(inputs.records, nws_surf_zone.CANONICAL_PREFIX).values():
        if record.normalized_values.get("rip_current_risk") != "HIGH":
            continue
        if (inputs.now is not None and record.effective_to is not None
                and inputs.now - record.effective_to > CLOSED_RETENTION):
            continue
        out.append(rip_current_alert(record, geo, index, inputs.now))
    return sorted(out, key=lambda a: a.alert_id)


def marine_alert(record: HazardRecord, geo: dict[str, dict[str, Any]], index: AssetIndex,
                 now: datetime | None) -> AlertEvent:
    values = record.normalized_values
    zones = list(values.get("zones") or [])
    coastal = list(values.get("coastal_municipios") or [])
    municipios = coastal or [f"PR marine zone {z}" for z in zones] or ["(PR waters)"]
    lat, lon = _place(coastal, geo)
    ended = record.effective_to is not None and now is not None and now >= record.effective_to
    closed = record.status == RecordStatus.TERMINATED or ended
    linked, sectors = link_impact(None, None, coastal, index, radius_km=None) if coastal else ([], [])
    significance = str(values.get("significance") or "")
    severity = MARINE_SEVERITY.get(significance, 2)
    start = record.effective_from or record.issued_at
    key = str(values.get("event_key") or record.source_record_id)
    review: Literal["accepted", "needs_review"] = "accepted" if values.get("phenomenon") else "needs_review"
    notes = [
        f"NWS {record.title_raw} for Puerto Rico marine zone(s) {', '.join(zones)} "
        f"(VTEC event {key}, action {values.get('vtec_action') or 'n/a'}).",
        f"Headline: {record.description_raw}." if record.description_raw else "",
        "Coastal municipios: marine zone polygon within 2 km of the municipio (PROXIMITY)."
        if coastal else "Offshore zone(s) only; no municipio borders them.",
        "Severity capped at 3: tropical and storm warnings reach the critical path via the NHC "
        "and land-zone NWS promoters.",
    ]
    return AlertEvent(
        alert_id=f"AYL_ALR_{(start or datetime(1970, 1, 1, tzinfo=timezone.utc)):%Y%m%d}{MARINE_MARKER}{_slug(key)}",
        module_id="WEATHER_HAZARD",
        event_type="hazard",
        status="closed" if closed else "active",
        source_title=f"{record.title_raw} — Puerto Rico waters ({', '.join(zones)})",
        source_ref=f"NWS-MARINE {record.source_record_id}; https://api.weather.gov/alerts/{record.source_record_id}",
        source_hash=None,
        published_at=_utc(record.issued_at) if record.issued_at else None,
        start_at=_utc(start) if start else _utc(now or datetime.now(timezone.utc)),
        end_at=_utc(record.effective_to) if closed and record.effective_to else None,
        asset_name=", ".join(zones) or "PR waters",
        asset_id=None,
        operator="NOAA/NWS WFO San Juan",
        municipalities=municipios,
        sectors_impacted=sectors,
        latitude=lat,
        longitude=lon,
        coord_confidence="approximate" if lat is not None else "unknown",
        severity=severity,
        confidence=85,
        ilap_score=None,
        covert_flags=[],
        gap_status="none",
        review_status=review,
        evidence_tier="T1",
        linked_asset_ids=merge_asset_ids([], linked),
        validation_notes=" ".join(n for n in notes if n),
    )


def marine_alerts(inputs: HydrometInputs | None, geo: dict[str, dict[str, Any]] | None = None,
                  index: AssetIndex | None = None) -> list[AlertEvent]:
    if inputs is None:
        return []
    geo, index = geo or {}, index or AssetIndex()
    out = []
    for record in current_by_event(inputs.records, nws_marine.CANONICAL_PREFIX).values():
        if (inputs.now is not None and record.status == RecordStatus.TERMINATED
                and record.effective_to is not None and inputs.now - record.effective_to > CLOSED_RETENTION):
            continue
        out.append(marine_alert(record, geo, index, inputs.now))
    return sorted(out, key=lambda a: a.alert_id)


def outdoor_alerts(inputs: HydrometInputs | None, geo: dict[str, dict[str, Any]] | None = None,
                   index: AssetIndex | None = None) -> list[AlertEvent]:
    """Every outdoor promoter, for the registry in :mod:`aguayluz.alert_promotion`."""
    return rip_current_alerts(inputs, geo, index) + marine_alerts(inputs, geo, index)


__all__ = [
    "CLOSED_RETENTION",
    "MARINE_MARKER",
    "MARINE_SEVERITY",
    "RIP_CURRENT_MARKER",
    "RIP_CURRENT_SEVERITY",
    "marine_alert",
    "marine_alerts",
    "outdoor_alerts",
    "rip_current_alert",
    "rip_current_alerts",
]
