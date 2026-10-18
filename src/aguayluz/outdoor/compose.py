"""Compose the per-municipio outdoor-conditions layer.

One row per municipio (78), each made of components that say where their value came
from, how it was bound to the municipio, and how current it is. :func:`compose` is pure
— every input is passed in — so tests can build any situation; :func:`load_inputs`
reads the committed files.

Component ``state`` vocabulary (never "safe"):

``REPORTED``       the source has a current value for this municipio
``NONE_ACTIVE``    an alert-type source is current and lists nothing for this municipio
                   (not a finding that conditions are benign)
``STALE``          the newest value is older than the component allows; it is shown
``NOT_COVERED``    the source does not cover this municipio (inland for marine sources,
                   no beaches named, no gauge, no reporting area within range)
``NOT_INGESTED``   the input is absent from this checkout and nothing could be carried
``NOT_CONFIGURED`` the source needs a credential that is not configured (AirNow)
``SOURCE_FAILED``  the source has failed and has never succeeded

A component whose input file is absent this run is carried forward from the previous
composition, marked ``carried_forward``, rather than flipping to NOT_INGESTED: the DRNA
and El Yunque inputs are produced by other jobs and are not in every checkout.

The summary ``level`` is ELEVATED, CAUTION, NO_DRIVER_REPORTED or INSUFFICIENT_DATA,
from published categories only (NWS rip current risk and heat-index chart, EPA UV and
AQI scales, NWS flood categories, official alerts). Conditions are context, not safety
advice.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..hazard_plane import HazardRecord, RecordStatus, current_records
from . import municipio_key

SCHEMA_VERSION = "aguayluz.outdoor-condition/v1"
AST = timezone(timedelta(hours=-4))

DATA_STATES = frozenset({"REPORTED", "NONE_ACTIVE", "STALE"})
STATES = frozenset({"REPORTED", "NONE_ACTIVE", "STALE", "NOT_COVERED", "NOT_INGESTED",
                    "NOT_CONFIGURED", "SOURCE_FAILED"})
LEVELS = ("ELEVATED", "CAUTION")

#: Nearest-point attachment range for buoys and AirNow reporting areas.
PROXIMITY_RANGE_KM = 40.0
#: DRNA publishes weekly; older than this, the latest publication is stale.
BEACH_STALE_DAYS = 14
#: A Stage IV 1-day field older than this is stale (it publishes after the 12Z day).
RAIN_STALE_DAYS = 3
#: Gauge observations older than this do not describe the river now.
GAUGE_STALE_HOURS = 6
#: An NHC advisory older than this has been superseded (they issue every 6 h).
NHC_CURRENT_HOURS = 12
NHC_ELEVATED_KM = 500.0
QUAKE_WINDOW_HOURS = 24
QUAKE_MIN_MAG = 3.5
QUAKE_RANGE_KM = 100.0
QUAKE_CAUTION = (4.5, 50.0)

FLOOD_ELEVATED = {"minor", "moderate", "major"}
_NWS_EVENT_RE = re.compile(r"event='([^']*)'")
_NWS_SEVERITY_RE = re.compile(r"severity=(\w+)")
_QUAKE_MAG_RE = re.compile(r"\bM(-?\d+(?:\.\d+)?)")

COMPONENTS = (
    "rip_current", "marine_alerts", "sea_state", "beach_water_quality", "uv", "heat",
    "air_quality", "rainfall_24h", "river_flood", "nws_alerts", "tropical_cyclone",
    "earthquakes", "access_closures",
)


@dataclass
class Inputs:
    """Everything one composition reads. ``None`` means the input file is absent."""

    municipios: list[dict[str, Any]]
    reference: dict[str, Any]
    registry: dict[str, Any]
    receipts: dict[str, Any]
    surf: list[dict[str, Any]] | None = None
    buoys: list[dict[str, Any]] | None = None
    uv: list[dict[str, Any]] | None = None
    heat: list[dict[str, Any]] | None = None
    aqi: list[dict[str, Any]] | None = None
    hydromet_records: list[HazardRecord] = field(default_factory=list)
    gauges: list[dict[str, Any]] | None = None
    service_events: list[dict[str, Any]] | None = None
    hazard_records: list[HazardRecord] | None = None
    access_conditions: list[dict[str, Any]] | None = None
    previous: dict[str, dict[str, Any]] = field(default_factory=dict)


# ------------------------------------------------------------------ helpers


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class _Sources:
    """Receipt-derived freshness per hydromet source."""

    def __init__(self, registry: dict[str, Any], receipts: dict[str, Any], now: datetime):
        self._by_id = {s.get("source_id"): s for s in registry.get("sources", [])}
        self._receipts = (receipts or {}).get("sources", receipts or {})
        self._now = now

    def entry(self, source_id: str) -> dict[str, Any]:
        return self._by_id.get(source_id) or {}

    def receipt(self, source_id: str) -> dict[str, Any] | None:
        return self._receipts.get(source_id)

    def status(self, source_id: str) -> str:
        """FRESH / STALE / FAILED / NEVER (same rule as aguayluz.hydromet.store.freshness)."""
        receipt = self.receipt(source_id)
        if not receipt:
            return "NEVER"
        last_success = _parse(receipt.get("last_success_utc"))
        if receipt.get("last_status") == "FAIL":
            return "FAILED"
        if last_success is None:
            return "NEVER"
        max_age = self.entry(source_id).get("max_age_seconds")
        age = (self._now - last_success).total_seconds()
        return "STALE" if isinstance(max_age, (int, float)) and age > max_age else "FRESH"

    def unavailable(self, source_id: str) -> str | None:
        """The state for a source with no usable data at all, or None if it has data."""
        receipt = self.receipt(source_id)
        if receipt and receipt.get("last_success_utc"):
            return None
        if self.entry(source_id).get("requires_secret") and not receipt:
            return "NOT_CONFIGURED"
        if receipt and receipt.get("last_status") == "FAIL":
            return "SOURCE_FAILED"
        return "NOT_INGESTED"


def _component(state: str, source_ids: Iterable[str], **fields: Any) -> dict[str, Any]:
    if state not in STATES:
        raise ValueError(f"unknown component state {state!r}")
    return {"state": state, "source_ids": sorted(set(source_ids)), **fields}


def _carry(previous: dict[str, Any] | None, name: str, source_ids: list[str],
           fallback: str = "NOT_INGESTED") -> dict[str, Any]:
    """The previous composition's component, marked carried forward, if it had data."""
    prior = ((previous or {}).get("components") or {}).get(name)
    if prior and prior.get("state") in DATA_STATES:
        return {**prior, "carried_forward": True,
                "carried_from": prior.get("carried_from") or (previous or {}).get("composed_at")}
    return _component(fallback, source_ids)


# --------------------------------------------------------------- components


def _rip_current(m: dict, inputs: Inputs, sources: _Sources, today: date) -> dict[str, Any]:
    sid = "nws_surf_zone"
    if inputs.surf is None:
        return _carry(inputs.previous.get(m["geoid"]), "rip_current", [sid],
                      sources.unavailable(sid) or "NOT_INGESTED")
    zone = next((z for z in inputs.surf if any(x.get("geoid") == m["geoid"] for x in z.get("municipios", []))), None)
    if zone is None:
        unavailable = sources.unavailable(sid)
        return _component(unavailable or "NOT_COVERED", [sid],
                          note=None if unavailable else
                          "The NWS Surf Zone Forecast names no beaches in this municipio.")

    def period(day: date) -> dict | None:
        return next((p for p in zone.get("periods", []) if p.get("detailed") and p.get("date") == day.isoformat()), None)

    def brief(p: dict | None) -> dict | None:
        if p is None:
            return None
        return {k: p.get(k) for k in ("date", "label", "rip_current_risk", "surf_min_ft",
                                      "surf_max_ft", "surf_height_text")}

    today_p = period(today)
    outlook = [{"date": p["date"], "surf_min_ft": p.get("surf_min_ft"), "surf_max_ft": p.get("surf_max_ft")}
               for p in zone.get("periods", [])
               if not p.get("detailed") and p.get("date") and p["date"] > today.isoformat()]
    return _component(
        "REPORTED" if today_p else "STALE", [sid],
        zone=zone.get("zone"), zone_name=zone.get("zone_name"),
        issued_at=zone.get("issued_at"), product_id=zone.get("product_id"),
        today=brief(today_p), tomorrow=brief(period(today + timedelta(days=1))),
        surf_outlook=outlook[:3],
        evidence_class=zone.get("binding_evidence"), binding_method=zone.get("binding_method"),
        source_status=sources.status(sid),
    )


def _coastal(inputs: Inputs) -> dict[str, list[dict]]:
    """geoid -> marine zones (with gap) bound to it in the reference file."""
    out: dict[str, list[dict]] = {}
    for zone in inputs.reference.get("marine_zones", []):
        for m in zone.get("municipios", []):
            out.setdefault(m["geoid"], []).append({"zone_id": zone["zone_id"], "name": zone.get("name"),
                                                   "distance_m": m.get("distance_m")})
    return out


def _marine_alerts(m: dict, inputs: Inputs, sources: _Sources, zones: list[dict], now: datetime) -> dict:
    sid = "nws_marine_alerts"
    if not zones:
        return _component("NOT_COVERED", [sid], note="No Puerto Rico marine zone borders this municipio.")
    unavailable = sources.unavailable(sid)
    if unavailable:
        return _component(unavailable, [sid])
    zone_ids = {z["zone_id"] for z in zones}
    owned = [r for r in inputs.hydromet_records if r.canonical_event_id.startswith("NWS_MARINE:")]
    alerts = []
    for record in current_records(owned):
        if record.status != RecordStatus.ACTIVE:
            continue
        if record.effective_to is not None and record.effective_to <= now:
            continue
        hit = sorted(set(record.normalized_values.get("zones") or []) & zone_ids)
        if hit:
            alerts.append({"event": record.title_raw, "zones": hit, "ends": _iso(record.effective_to),
                           "headline": record.description_raw, "record_id": record.record_id})
    alerts.sort(key=lambda a: (a["event"], a["record_id"]))
    status = sources.status(sid)
    state = "STALE" if status in {"STALE", "FAILED"} else ("REPORTED" if alerts else "NONE_ACTIVE")
    return _component(state, [sid], alerts=alerts, marine_zones=sorted(zone_ids),
                      evidence_class="PROXIMITY", binding_method="marine_zone_within_2km",
                      source_status=status)


def _nearest(rows: Iterable[dict], lat: float, lon: float) -> tuple[dict, float] | None:
    best = None
    for row in rows:
        if not isinstance(row.get("lat"), (int, float)) or not isinstance(row.get("lon"), (int, float)):
            continue
        gap = haversine_km(lat, lon, row["lat"], row["lon"])
        if best is None or gap < best[1]:
            best = (row, gap)
    return best


def _sea_state(m: dict, inputs: Inputs, sources: _Sources, coastal: bool, now: datetime) -> dict:
    sid = "ndbc_buoys"
    if not coastal:
        return _component("NOT_COVERED", [sid], note="Inland municipio.")
    if inputs.buoys is None:
        return _carry(inputs.previous.get(m["geoid"]), "sea_state", [sid],
                      sources.unavailable(sid) or "NOT_INGESTED")
    hit = _nearest(inputs.buoys, m["lat"], m["lon"])
    if hit is None or hit[1] > PROXIMITY_RANGE_KM:
        return _component("NOT_COVERED", [sid],
                          note=f"No Puerto Rico buoy within {PROXIMITY_RANGE_KM:.0f} km.")
    buoy, gap = hit
    stale_after = float(sources.entry(sid).get("observation_stale_after_seconds") or 10800)
    observed = _parse(buoy.get("observed_at"))
    stale = observed is None or (now - observed).total_seconds() > stale_after
    values = buoy.get("observed") or {}
    return _component(
        "STALE" if stale else "REPORTED", [sid],
        station=buoy.get("station"), station_name=buoy.get("name"), distance_km=round(gap, 1),
        observed_at=buoy.get("observed_at"),
        **{k: values.get(k) for k in ("wave_height_ft", "dominant_period_s", "mean_wave_direction_deg",
                                      "water_temp_f", "wind_speed_kt", "wind_gust_kt", "wind_direction_deg")},
        evidence_class="PROXIMITY", binding_method="nearest_buoy_to_internal_point",
        note="Offshore point observation; null means the buoy did not report that value.",
        source_status=sources.status(sid),
    )


def _by_geoid(rows: list[dict] | None) -> dict[str, dict]:
    return {r["geoid"]: r for r in rows or [] if r.get("geoid")}


def _uv(m: dict, inputs: Inputs, sources: _Sources, today: date) -> dict:
    sid = "epa_uv"
    if inputs.uv is None:
        return _carry(inputs.previous.get(m["geoid"]), "uv", [sid], sources.unavailable(sid) or "NOT_INGESTED")
    row = _by_geoid(inputs.uv).get(m["geoid"])
    if row is None:
        return _component(sources.unavailable(sid) or "NOT_COVERED", [sid])
    current = (row.get("forecast_date") or "") >= today.isoformat()
    return _component(
        "REPORTED" if current else "STALE", [sid],
        uv_index=row.get("uv_index"), uv_category=row.get("uv_category"), uv_alert=row.get("uv_alert"),
        forecast_date=row.get("forecast_date"), zip=row.get("zip"),
        carried_forward_by_source=bool(row.get("carried_forward")),
        evidence_class=row.get("binding_evidence"), binding_method=row.get("binding_method"),
        source_status=sources.status(sid),
    )


def _heat(m: dict, inputs: Inputs, sources: _Sources, now: datetime) -> dict:
    sid = "nws_gridpoint_heat"
    if inputs.heat is None:
        return _carry(inputs.previous.get(m["geoid"]), "heat", [sid], sources.unavailable(sid) or "NOT_INGESTED")
    row = _by_geoid(inputs.heat).get(m["geoid"])
    if row is None:
        return _component(sources.unavailable(sid) or "NOT_COVERED", [sid])
    start = _parse(row.get("window_start"))
    current = start is not None and (now - start) <= timedelta(hours=36)
    return _component(
        "REPORTED" if current else "STALE", [sid],
        **{k: row.get(k) for k in ("heat_index_max_f_24h", "heat_band_24h", "heat_index_peak_at_24h",
                                   "heat_index_max_f_48h", "heat_band_48h", "wbgt_max_f_24h",
                                   "max_temp_max_f_24h", "window_start", "update_time")},
        carried_forward_by_source=bool(row.get("carried_forward")),
        evidence_class=row.get("binding_evidence"), binding_method=row.get("binding_method"),
        geometry_precision="REPRESENTATIVE_POINT", source_status=sources.status(sid),
        note="NWS heat-index chart bands; official Heat Advisories are listed under nws_alerts.",
    )


def _air_quality(m: dict, inputs: Inputs, sources: _Sources, now: datetime) -> dict:
    sid = "airnow"
    if inputs.aqi is None:
        unavailable = sources.unavailable(sid) or "NOT_INGESTED"
        if unavailable == "NOT_CONFIGURED":
            return _component(unavailable, [sid], note="AirNow needs the AIRNOW_API_KEY secret.")
        return _carry(inputs.previous.get(m["geoid"]), "air_quality", [sid], unavailable)
    areas: dict[str, list[dict]] = {}
    for row in inputs.aqi:
        areas.setdefault(row["reporting_area"], []).append(row)
    points = [{"area": a, "lat": rows[0].get("lat"), "lon": rows[0].get("lon")} for a, rows in areas.items()]
    hit = _nearest(points, m["lat"], m["lon"])
    if hit is None or hit[1] > PROXIMITY_RANGE_KM:
        return _component("NOT_COVERED", [sid],
                          note=f"No AirNow reporting area within {PROXIMITY_RANGE_KM:.0f} km.")
    area_rows = areas[hit[0]["area"]]
    worst = max(area_rows, key=lambda r: r.get("aqi") or -1)
    observed = _parse(worst.get("observed_at"))
    current = observed is not None and (now - observed) <= timedelta(hours=3)
    return _component(
        "REPORTED" if current else "STALE", [sid],
        reporting_area=hit[0]["area"], distance_km=round(hit[1], 1),
        aqi=worst.get("aqi"), category=worst.get("category"), parameter=worst.get("parameter"),
        pollutants=sorted(({"parameter": r["parameter"], "aqi": r["aqi"], "category": r.get("category")}
                           for r in area_rows), key=lambda r: r["parameter"]),
        observed_at=worst.get("observed_at"),
        evidence_class="PROXIMITY", binding_method="nearest_reporting_area_to_internal_point",
        note="AirNow data are preliminary and unvalidated.", source_status=sources.status(sid),
    )


def _beach(m: dict, inputs: Inputs, coastal: bool, now: datetime) -> dict:
    sid = "drna_beach_monitoring"
    if not coastal:
        return _component("NOT_COVERED", [sid], note="Inland municipio.")
    if inputs.hazard_records is None:
        return _carry(inputs.previous.get(m["geoid"]), "beach_water_quality", [sid])
    beach = [r for r in current_records([r for r in inputs.hazard_records
                                         if r.canonical_event_id.startswith("DRNA_BEACH:")])]
    issued = {r.record_id: r.issued_at for r in beach if r.issued_at is not None}
    dated = [r for r in beach if r.record_id in issued]
    if not dated:
        return _carry(inputs.previous.get(m["geoid"]), "beach_water_quality", [sid])
    latest_at = max(issued.values())
    post_id = next(r.raw_attributes.get("post_id") for r in dated if r.issued_at == latest_at)
    latest = [r for r in dated if r.raw_attributes.get("post_id") == post_id]
    mine = [r for r in latest
            if r.hazard_type in {"BEACH_ENTEROCOCCI_BAV_EXCEEDANCE", "BEACH_WATER_QUALITY_ADVISORY_OTHER_OBSERVATION"}
            and municipio_key(r.raw_attributes.get("municipality_raw")) == municipio_key(m["name"])]
    advisories = sorted(({"beach": r.raw_attributes.get("beach_name"), "station_id": r.raw_attributes.get("station_id"),
                          "hazard_type": r.hazard_type, "bav_value": r.raw_attributes.get("bav_value"),
                          "record_id": r.record_id} for r in mine), key=lambda a: (a["beach"] or "", a["record_id"]))
    stale = now - latest_at > timedelta(days=BEACH_STALE_DAYS)
    return _component(
        "STALE" if stale else ("REPORTED" if advisories else "NONE_ACTIVE"), [sid],
        publication_at=_iso(latest_at), post_id=post_id, advisories=advisories,
        evidence_class="AUTHORITATIVE_BINDING", binding_method="drna.municipality_text == municipio",
        note="DRNA lists only the beaches it samples; no advisory is not a water-quality finding.",
    )


def _river(m: dict, inputs: Inputs, sources: _Sources, now: datetime) -> dict:
    sid = "nwps_gauges"
    if inputs.gauges is None:
        return _carry(inputs.previous.get(m["geoid"]), "river_flood", [sid], sources.unavailable(sid) or "NOT_INGESTED")
    mine = [g for g in inputs.gauges if g.get("geoid") == m["geoid"]]
    if not mine:
        return _component("NOT_COVERED", [sid], note="No NWPS gauge is bound to this municipio.")
    fresh = []
    for g in mine:
        valid = _parse((g.get("observed") or {}).get("valid_time"))
        if valid is not None and now - valid <= timedelta(hours=GAUGE_STALE_HOURS):
            fresh.append(g)
    flooding = sorted(({"lid": g["lid"], "name": g.get("name"), "flood_category": g.get("flood_category")}
                       for g in fresh if g.get("flood_category") in {"action", *FLOOD_ELEVATED}),
                      key=lambda g: g["lid"])
    order = ["action", "minor", "moderate", "major"]
    worst = max((g["flood_category"] for g in flooding), key=order.index, default=None)
    return _component(
        "REPORTED" if fresh else "STALE", [sid],
        gauges_total=len(mine), gauges_current=len(fresh), gauges_in_flood=flooding, worst_category=worst,
        evidence_class="POINT_IN_POLYGON", binding_method="nwps_gauge_bound_to_municipio",
        source_status=sources.status(sid),
    )


def _rain(m: dict, inputs: Inputs, sources: _Sources, today: date) -> dict:
    from ..hazard_adapters.stage_iv_qpe import heavy_rain_severity

    sid = "stage_iv_pr"
    mine = [r for r in current_records([r for r in inputs.hydromet_records
                                        if r.canonical_event_id.startswith("STAGEIV_QPE:1day:")])
            if r.municipality_id == m["geoid"]]
    if not mine:
        return _component(sources.unavailable(sid) or "NOT_COVERED", [sid])
    latest = max(mine, key=lambda r: str(r.normalized_values.get("data_date") or ""))
    values = latest.normalized_values
    day = date.fromisoformat(values["data_date"]) if values.get("data_date") else None
    stale = day is None or (today - day).days > RAIN_STALE_DAYS
    return _component(
        "STALE" if stale else "REPORTED", [sid],
        data_date=values.get("data_date"), obs_mean_in=values.get("obs_mean_in"),
        obs_max_in=values.get("obs_max_in"), pct_of_normal=values.get("pct_of_normal"),
        heavy_rain_severity=heavy_rain_severity(values),
        evidence_class="CERTIFIED_GEOMETRY", binding_method=values.get("method"),
        note="Stage IV 12Z-12Z observed rainfall (post-event), not a forecast.",
        source_status=sources.status(sid),
    )


def _nws_land_alerts(inputs: Inputs, now: datetime) -> dict[str, list[dict]] | None:
    """geoid -> active NWS land-zone alerts, bound via areaDesc names."""
    if inputs.service_events is None:
        return None
    zone_members = {municipio_key(z.get("name")): z.get("municipio_geoids", [])
                    for z in inputs.reference.get("forecast_zones", [])}
    by_name = {municipio_key(m["name"]): m["geoid"] for m in inputs.municipios}
    out: dict[str, list[dict]] = {}
    for event in inputs.service_events:
        if not str(event.get("source_ref") or "").startswith("urn:oid:"):
            continue
        start, end = _parse(event.get("start_time")), _parse(event.get("end_time"))
        if start is None or start > now or end is None or end <= now:
            continue
        name = (_NWS_EVENT_RE.search(event.get("status_text") or "") or [None, None])[1]
        if not name:
            continue
        severity = (_NWS_SEVERITY_RE.search(event.get("status_text") or "") or [None, None])[1]
        for raw in str(event.get("affected_area") or "").split(";"):
            token = municipio_key(re.sub(r",\s*PR$", "", raw.strip()))
            if token in by_name:
                targets, method = [by_name[token]], "nws.areaDesc names the municipio"
            elif token in zone_members:
                targets, method = zone_members[token], "nws.areaDesc names the forecast zone holding the internal point"
            else:
                continue
            for geoid in targets:
                out.setdefault(geoid, []).append({"event": name, "severity": severity,
                                                  "starts": _iso(start), "ends": _iso(end),
                                                  "event_id": event.get("event_id"), "binding_method": method})
    for alerts in out.values():
        alerts.sort(key=lambda a: (a["event"], a["event_id"] or ""))
        deduped, seen = [], set()
        for a in alerts:
            if a["event_id"] not in seen:
                seen.add(a["event_id"])
                deduped.append(a)
        alerts[:] = deduped
    return out


def _nws_alerts(m: dict, inputs: Inputs, land: dict[str, list[dict]] | None) -> dict:
    sid = "nws_alerts"
    if land is None:
        return _carry(inputs.previous.get(m["geoid"]), "nws_alerts", [sid])
    alerts = land.get(m["geoid"], [])
    return _component("REPORTED" if alerts else "NONE_ACTIVE", [sid], alerts=alerts,
                      evidence_class="AUTHORITATIVE_BINDING",
                      note="Official NWS San Juan land-zone products (scripts/ingest_nws_alerts.py).")


def _storms(inputs: Inputs, now: datetime) -> list[dict] | None:
    if inputs.service_events is None:
        return None
    latest: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for event in inputs.service_events:
        ref = str(event.get("source_ref") or "")
        if not ref.startswith("NHC-"):
            continue
        start = _parse(event.get("start_time"))
        if start is None or now - start > timedelta(hours=NHC_CURRENT_HOURS) or start > now + timedelta(hours=1):
            continue
        storm = ref.split(" ", 1)[0]
        if storm not in latest or start > latest[storm][0]:
            latest[storm] = (start, event)
    return [latest[k][1] for k in sorted(latest)]


def _tropical(m: dict, inputs: Inputs, storms: list[dict] | None) -> dict:
    sid = "nhc_storms"
    if storms is None:
        return _carry(inputs.previous.get(m["geoid"]), "tropical_cyclone", [sid])
    rows = []
    for event in storms:
        if not isinstance(event.get("lat"), (int, float)) or not isinstance(event.get("lon"), (int, float)):
            continue
        rows.append({"storm": str(event["source_ref"]).split(" ", 1)[0].removeprefix("NHC-"),
                     "status_text": event.get("status_text"), "advisory_at": event.get("start_time"),
                     "distance_km": round(haversine_km(m["lat"], m["lon"], event["lat"], event["lon"]))})
    return _component("REPORTED" if rows else "NONE_ACTIVE", [sid], storms=rows,
                      note="Atlantic systems inside the Puerto Rico approach corridor (NHC).")


def _quakes(m: dict, inputs: Inputs, now: datetime) -> dict:
    sid = "usgs_quakes"
    if inputs.service_events is None:
        return _carry(inputs.previous.get(m["geoid"]), "earthquakes", [sid])
    rows: list[dict[str, Any]] = []
    for event in inputs.service_events:
        if not str(event.get("source_ref") or "").startswith("USGS-EQ:"):
            continue
        start = _parse(event.get("start_time"))
        if start is None or now - start > timedelta(hours=QUAKE_WINDOW_HOURS) or start > now:
            continue
        mag_match = _QUAKE_MAG_RE.search(event.get("status_text") or "")
        if not mag_match or float(mag_match.group(1)) < QUAKE_MIN_MAG:
            continue
        if not isinstance(event.get("lat"), (int, float)) or not isinstance(event.get("lon"), (int, float)):
            continue
        gap = haversine_km(m["lat"], m["lon"], event["lat"], event["lon"])
        if gap <= QUAKE_RANGE_KM:
            rows.append({"magnitude": float(mag_match.group(1)), "place": event.get("affected_area"),
                         "time": _iso(start), "distance_km": round(gap, 1), "event_id": event.get("event_id")})
    rows.sort(key=lambda r: (-float(r["magnitude"]), str(r["event_id"] or "")))
    return _component("REPORTED" if rows else "NONE_ACTIVE", [sid], recent=rows,
                      note=f"M{QUAKE_MIN_MAG}+ within {QUAKE_RANGE_KM:.0f} km in the last {QUAKE_WINDOW_HOURS} h (USGS).")


def _access(m: dict, inputs: Inputs, now: datetime) -> dict:
    sid = "usfs_el_yunque_access"
    assets = {a["semantic_key"]: a for a in inputs.reference.get("access_assets", []) if a.get("semantic_key")}
    covered = any(m["geoid"] in {x["geoid"] for x in a.get("municipios", [])} for a in assets.values())
    if not covered:
        return _component("NOT_COVERED", [sid], note="No certified El Yunque access asset in this municipio.")
    if inputs.access_conditions is None:
        return _carry(inputs.previous.get(m["geoid"]), "access_closures", [sid])
    rows = []
    for cond in inputs.access_conditions:
        asset = assets.get(cond.get("asset_key"))
        if asset is None or m["geoid"] not in {x["geoid"] for x in asset.get("municipios", [])}:
            continue
        status = cond.get("status")
        end, start = _parse(cond.get("effective_end")), _parse(cond.get("effective_start"))
        in_force = status in {"closed", "restricted"} and (end is None or end > now)
        upcoming = status == "scheduled" and start is not None and start > now
        if not (in_force or upcoming):
            continue
        rows.append({"asset": asset.get("asset_name"), "status": status, "scope_name": cond.get("scope_name"),
                     "effective_start": cond.get("effective_start"), "effective_end": cond.get("effective_end"),
                     "source_url": cond.get("source_url"), "condition_id": cond.get("condition_id")})
    rows.sort(key=lambda r: (r["asset"] or "", r["condition_id"] or ""))
    return _component("REPORTED" if rows else "NONE_ACTIVE", [sid], closures=rows,
                      evidence_class="CERTIFIED_GEOMETRY",
                      note="USDA Forest Service orders for certified El Yunque assets only.")


# ---------------------------------------------------------------- summary


def drivers(components: dict[str, dict]) -> list[dict[str, str]]:
    """Published-category drivers from REPORTED components only."""
    out: list[dict[str, str]] = []

    def add(name: str, level: str, reason: str) -> None:
        out.append({"component": name, "level": level, "reason": reason})

    def reported(name: str) -> dict | None:
        c = components.get(name) or {}
        return c if c.get("state") == "REPORTED" else None

    if (c := reported("rip_current")) and c.get("today"):
        risk = c["today"].get("rip_current_risk")
        if risk == "HIGH":
            add("rip_current", "ELEVATED", "NWS rip current risk High today")
        elif risk == "MODERATE":
            add("rip_current", "CAUTION", "NWS rip current risk Moderate today")
    if (c := reported("marine_alerts")) and c.get("alerts"):
        add("marine_alerts", "ELEVATED", ", ".join(sorted({a["event"] for a in c["alerts"]})))
    if (c := reported("beach_water_quality")) and c.get("advisories"):
        add("beach_water_quality", "ELEVATED", f"DRNA advisory at {len(c['advisories'])} beach(es)")
    if c := reported("heat"):
        band = c.get("heat_band_24h")
        if band in {"DANGER", "EXTREME_DANGER"}:
            add("heat", "ELEVATED", f"Heat index {c.get('heat_index_max_f_24h')} °F ({band.replace('_', ' ').title()})")
        elif band == "EXTREME_CAUTION":
            add("heat", "CAUTION", f"Heat index {c.get('heat_index_max_f_24h')} °F (Extreme Caution)")
    if c := reported("uv"):
        cat = c.get("uv_category")
        if cat == "EXTREME":
            add("uv", "ELEVATED", f"UV index {c.get('uv_index'):g} (Extreme)")
        elif cat in {"HIGH", "VERY_HIGH"}:
            add("uv", "CAUTION", f"UV index {c.get('uv_index'):g} ({cat.replace('_', ' ').title()})")
    if c := reported("air_quality"):
        cat = c.get("category")
        if cat in {"UNHEALTHY", "VERY_UNHEALTHY", "HAZARDOUS"}:
            add("air_quality", "ELEVATED", f"AQI {c.get('aqi')} {c.get('parameter')} ({cat.replace('_', ' ').title()})")
        elif cat == "UNHEALTHY_FOR_SENSITIVE_GROUPS":
            add("air_quality", "CAUTION", f"AQI {c.get('aqi')} {c.get('parameter')} (Unhealthy for Sensitive Groups)")
    if (c := reported("river_flood")) and c.get("worst_category"):
        level = "ELEVATED" if c["worst_category"] in FLOOD_ELEVATED else "CAUTION"
        add("river_flood", level, f"River gauge at {c['worst_category']} flood stage")
    if (c := reported("rainfall_24h")) and c.get("heavy_rain_severity"):
        level = "ELEVATED" if c["heavy_rain_severity"] >= 3 else "CAUTION"
        add("rainfall_24h", level, f"Heavy rain: {c.get('obs_mean_in')} in mean, {c.get('obs_max_in')} in max")
    if (c := reported("nws_alerts")) and c.get("alerts"):
        events = sorted({a["event"] for a in c["alerts"]})
        level = "ELEVATED" if any(e.endswith("Warning") for e in events) else "CAUTION"
        add("nws_alerts", level, ", ".join(events))
    if (c := reported("tropical_cyclone")) and c.get("storms"):
        nearest = min(s["distance_km"] for s in c["storms"])
        add("tropical_cyclone", "ELEVATED" if nearest <= NHC_ELEVATED_KM else "CAUTION",
            f"Tropical system {nearest} km away")
    if (c := reported("earthquakes")) and c.get("recent"):
        mag, rng = QUAKE_CAUTION
        felt = [q for q in c["recent"] if q["magnitude"] >= mag and q["distance_km"] <= rng]
        if felt:
            add("earthquakes", "CAUTION", f"M{felt[0]['magnitude']:g} earthquake {felt[0]['distance_km']} km away")
    if (c := reported("access_closures")) and c.get("closures"):
        add("access_closures", "CAUTION", f"{len(c['closures'])} El Yunque access order(s)")
    return out


def summarize(components: dict[str, dict]) -> dict[str, Any]:
    found = drivers(components)
    levels = {d["level"] for d in found}
    with_data = [n for n, c in components.items() if c.get("state") in {"REPORTED", "NONE_ACTIVE"}]
    if "ELEVATED" in levels:
        level = "ELEVATED"
    elif "CAUTION" in levels:
        level = "CAUTION"
    elif len(with_data) >= 4:
        level = "NO_DRIVER_REPORTED"
    else:
        level = "INSUFFICIENT_DATA"
    return {
        "level": level,
        "drivers": found,
        "components_with_data": sorted(with_data),
        "stale_components": sorted(n for n, c in components.items() if c.get("state") == "STALE"),
        "unavailable_components": sorted(n for n, c in components.items()
                                         if c.get("state") in {"NOT_INGESTED", "NOT_CONFIGURED", "SOURCE_FAILED"}),
    }


def _as_of(components: dict[str, dict]) -> str | None:
    keys = ("observed_at", "issued_at", "window_start", "publication_at", "advisory_at")
    stamps = []
    for c in components.values():
        if c.get("state") not in DATA_STATES:
            continue
        for k in keys:
            if (v := _parse(c.get(k))) is not None:
                stamps.append(v)
        if c.get("forecast_date"):
            stamps.append(datetime.fromisoformat(c["forecast_date"]).replace(tzinfo=AST))
    return _iso(max(stamps)) if stamps else None


# ---------------------------------------------------------------- compose


def compose(inputs: Inputs, now: datetime) -> list[dict[str, Any]]:
    """One outdoor-condition row per municipio, sorted by GEOID."""
    now = now.astimezone(timezone.utc)
    today = now.astimezone(AST).date()
    sources = _Sources(inputs.registry, inputs.receipts, now)
    coastal_zones = _coastal(inputs)
    surf_geoids = {x["geoid"] for z in inputs.surf or [] for x in z.get("municipios", [])}
    land = _nws_land_alerts(inputs, now)
    storms = _storms(inputs, now)
    rows = []
    for m in sorted(inputs.municipios, key=lambda x: x["geoid"]):
        zones = coastal_zones.get(m["geoid"], [])
        coastal = bool(zones) or m["geoid"] in surf_geoids
        components = {
            "rip_current": _rip_current(m, inputs, sources, today),
            "marine_alerts": _marine_alerts(m, inputs, sources, zones, now),
            "sea_state": _sea_state(m, inputs, sources, coastal, now),
            "beach_water_quality": _beach(m, inputs, coastal, now),
            "uv": _uv(m, inputs, sources, today),
            "heat": _heat(m, inputs, sources, now),
            "air_quality": _air_quality(m, inputs, sources, now),
            "rainfall_24h": _rain(m, inputs, sources, today),
            "river_flood": _river(m, inputs, sources, now),
            "nws_alerts": _nws_alerts(m, inputs, land),
            "tropical_cyclone": _tropical(m, inputs, storms),
            "earthquakes": _quakes(m, inputs, now),
            "access_closures": _access(m, inputs, now),
        }
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "condition_id": f"AYL_OUTDOOR_{m['geoid']}",
            "geoid": m["geoid"],
            "municipio": m["name"],
            "lat": m["lat"],
            "lon": m["lon"],
            "geometry_precision": "REPRESENTATIVE_POINT",
            "coastal": coastal,
            "composed_at": _iso(now),
            "as_of": _as_of(components),
            "summary": summarize(components),
            "components": components,
            "scope_note": "Conditions context from public sources, not safety advice; "
                          "a component without data says why.",
        })
    return rows


# ------------------------------------------------------------------- load


def load_inputs(data_dir: Any = None, *, reference_path: Any = None, registry_path: Any = None) -> Inputs:
    """Read every committed input; an absent file becomes ``None``."""
    from pathlib import Path

    from .. import DATA_DIR
    from ..hydromet import store
    from . import conditions_path, load_municipios, load_reference, state_path

    base = Path(data_dir) if data_dir is not None else DATA_DIR

    def optional(path: Path) -> list[dict] | None:
        return store.read_jsonl(path) if path.is_file() else None

    hazard_path = base / "hazard_records.jsonl"
    hazard = None
    if hazard_path.is_file():
        hazard = [HazardRecord.model_validate(r) for r in store.read_jsonl(hazard_path)]
    previous = {r["geoid"]: r for r in optional(conditions_path(base)) or [] if r.get("geoid")}
    return Inputs(
        municipios=load_municipios(),
        reference=load_reference(reference_path),
        registry=store.load_source_registry(registry_path),
        receipts=store.load_receipts(base),
        surf=optional(state_path("nws_surf_zone", base)),
        buoys=optional(state_path("ndbc_buoys", base)),
        uv=optional(state_path("epa_uv", base)),
        heat=optional(state_path("nws_gridpoint_heat", base)),
        aqi=optional(state_path("airnow", base)),
        hydromet_records=store.load_records(base),
        gauges=optional(store.hydromet_paths(base).gauge_state),
        service_events=optional(base / "service_events.jsonl"),
        hazard_records=hazard,
        access_conditions=optional(base / "access_conditions.jsonl"),
        previous=previous,
    )


__all__ = [
    "COMPONENTS",
    "Inputs",
    "LEVELS",
    "SCHEMA_VERSION",
    "STATES",
    "compose",
    "drivers",
    "haversine_km",
    "load_inputs",
    "summarize",
]
