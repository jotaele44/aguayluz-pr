"""Canonical AguaYLuz ASGI application with metric-safe monitoring contracts."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.backend import main as legacy
from server.backend.cave_karst_api import router as cave_karst_router
from server.backend.environmental_exposure_api import router as environmental_exposure_router
from server.backend.monitoring_alert_operations import federation_alert_export, lifecycle_alerts
from server.backend.monitoring_incident_ledger import (
    ALLOWED_EVENTS,
    append_event,
    escalation_candidates,
    federation_delta,
    materialized_state,
    notification_outbox,
    read_events,
    replay,
    timeline,
    verify_chain,
)
from server.backend.monitoring_quality import (
    SERIES_METADATA_REGISTRY,
    series_keys_for_metric,
    series_policy,
    series_quality,
)
from server.backend.regulatory_api import router as regulatory_router
from server.backend.water_disruption_api import router as water_disruption_router


def _is_legacy_readings(route: Any) -> bool:
    return getattr(route, "path", None) == "/readings" and "GET" in getattr(route, "methods", set())


def _is_legacy_municipio_summary(route: Any) -> bool:
    return getattr(route, "path", None) == "/municipios/{name}/summary" and "GET" in getattr(route, "methods", set())


app = FastAPI(title=legacy.app.title)
app.router.routes.extend(
    route for route in legacy.app.router.routes
    if not _is_legacy_readings(route) and not _is_legacy_municipio_summary(route)
)
app.exception_handlers.update(legacy.app.exception_handlers)
app.dependency_overrides.update(legacy.app.dependency_overrides)
for middleware in reversed(legacy.app.user_middleware):
    app.add_middleware(middleware.cls, *middleware.args, **middleware.kwargs)
app.include_router(water_disruption_router)
app.include_router(cave_karst_router)
app.include_router(regulatory_router)
app.include_router(environmental_exposure_router)

READING_VECTOR_REGISTRY: dict[str, dict[str, Any]] = {
    "reservoir": {"path": legacy.DATA / "reservoir_levels.jsonl", "metrics": {"reservoir_elevation": {"units": {"ft"}}, "reservoir_storage_pct": {"units": {"%"}}, "streamflow": {"units": {"ft3/s", "ft³/s"}}, "gage_height": {"units": {"ft"}}}, "metric_required": True},
    "groundwater": {"path": legacy.DATA / "groundwater_levels.jsonl", "metrics": {"groundwater_level": {"units": {"ft"}}}, "metric_required": False},
    "coastal": {"path": legacy.DATA / "coastal_levels.jsonl", "metrics": {"coastal_water_level": {"units": {"ft"}}}, "metric_required": False},
    "drought": {"path": legacy.DATA / "drought_conditions.jsonl", "metrics": {"drought_category": {"units": {"category"}}}, "metric_required": False},
    "precipitation": {"path": legacy.DATA / "precipitation_conditions.jsonl", "metrics": {"precipitation_pct_normal": {"units": {"%"}}}, "metric_required": False},
    # Discrete USGS field measurements — the wells the Daily Values service cannot see.
    "usgs_field_measurements": {"path": legacy.DATA / "usgs_field_measurements_readings.jsonl", "metrics": {"groundwater_level": {"units": {"ft"}}}, "metric_required": False},
    # Annual peak flow, 1899->. `ft^3/s` is load-bearing and NOT a typo: the USGS OGC API
    # publishes `unit_of_measure: "ft^3/s"` and ingest_usgs_peaks.py stores it verbatim, so
    # a whitelist of only {"ft3/s","ft³/s"} silently drops all 4,104 streamflow peaks —
    # _series_rows filters on exact unit membership. Regression-tested.
    "usgs_peaks": {"path": legacy.DATA / "usgs_peaks_readings.jsonl", "metrics": {"streamflow": {"units": {"ft^3/s", "ft3/s", "ft³/s"}}, "gage_height": {"units": {"ft"}}}, "metric_required": True},
}

# `utility_asset.asset_id` prefix -> the reading `kind`(s) whose `site_no` it identifies.
# One physical USGS stream gage backs both the daily-values `reservoir` vector
# (ingest_usgs_levels.py) and the historical `usgs_peaks` vector — ingest_usgs_peaks.py's
# own `asset_id_for()` docstring says it "owns no assets" and references the `USGS_*`
# asset the levels ingest maintains, so both kinds share one prefix. Every other kind has
# its own distinct prefix (ingest_usgs_groundwater.py: USGSGW_, ingest_usgs_field_
# measurements.py: USGSFM_, ingest_noaa_tides.py: NOAA_, ingest_precip_ncei.py: NCEI_,
# ingest_drought_usdm.py: USDM_ with site_no == municipio FIPS == pr_municipios.geojson's
# `geoid`). Longer/more specific prefixes are listed first defensively, though none of
# these actually collide as string prefixes of one another.
ASSET_PREFIX_TO_SOURCE_KINDS: dict[str, list[str]] = {
    "USGSGW_": ["groundwater"],
    "USGSFM_": ["usgs_field_measurements"],
    "USGS_": ["reservoir", "usgs_peaks"],
    "NOAA_": ["coastal"],
    "NCEI_": ["precipitation"],
    "USDM_": ["drought"],
}


def _site_no_for_asset(asset_id: str) -> str | None:
    for prefix in ASSET_PREFIX_TO_SOURCE_KINDS:
        if asset_id.startswith(prefix):
            return asset_id[len(prefix):]
    return None


def _source_kinds_for_asset(asset_id: str) -> list[str]:
    for prefix, kinds in ASSET_PREFIX_TO_SOURCE_KINDS.items():
        if asset_id.startswith(prefix):
            return kinds
    return []


#: Kinds whose MONITORING_SERIES entries (dashboard/src/lib/monitoring.js) genuinely split
#: one metric into multiple parallel, non-comparable series by `parameter_code` —
#: precipitation's 30d vs 90d windows. Grouping by parameter_code must be scoped to just
#: these: for every other kind, `parameter_code` is either a stable USGS constant (safe to
#: ignore) or, for drought, the classification LABEL itself
#: (scripts/ingest_drought_usdm.py writes "D0"/"D1"/... as parameter_code) — grouping by it
#: there would treat every week's classification as its own "parameter" and surface stale
#: duplicates instead of the single latest reading.
PARAMETER_CODE_SPLIT_KINDS = frozenset({"precipitation"})


def _monitoring_readings_for_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Latest reading per (site, kind, metric[, parameter_code]) for a set of municipio assets.

    Returns raw rows rather than pre-mapping to the dashboard's MONITORING_SERIES keys —
    `dashboard/src/lib/monitoring.js` already owns that mapping, so duplicating it here
    would just be a second place to keep in sync.
    """
    items: list[dict[str, Any]] = []
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        site_no = _site_no_for_asset(asset_id)
        if site_no is None:
            continue
        for kind in _source_kinds_for_asset(asset_id):
            vector = READING_VECTOR_REGISTRY.get(kind)
            if vector is None:
                continue
            split_by_param = kind in PARAMETER_CODE_SPLIT_KINDS
            for metric in vector["metrics"]:
                rows = [row for row in _series_rows(kind, metric) if str(row.get("site_no") or "") == site_no]
                latest_by_param: dict[str, dict[str, Any]] = {}
                for row in rows:
                    pcode = str(row.get("parameter_code") or "") if split_by_param else ""
                    current = latest_by_param.get(pcode)
                    if current is None or str(row.get("observed_date") or "") > str(current.get("observed_date") or ""):
                        latest_by_param[pcode] = row
                for row in latest_by_param.values():
                    items.append({
                        "kind": kind,
                        "metric": metric,
                        "parameter_code": row.get("parameter_code"),
                        "value": row.get("value"),
                        "unit": row.get("unit"),
                        "observed_date": row.get("observed_date"),
                        "provisional": row.get("provisional"),
                        "site_no": site_no,
                        "asset_id": asset_id,
                    })
    return items


@app.get("/municipios/{name}/summary")
def municipio_summary(name: str) -> JSONResponse:
    name_lower = name.lower()
    mun_assets = [a for a in legacy._assets if (a.get("municipality") or "").lower() == name_lower]
    mun_events = [
        e for e in legacy._events
        if (e.get("municipality") or "").lower() == name_lower
        or name_lower in (e.get("affected_area") or "").lower()
    ]
    active = sum(1 for a in mun_assets if a.get("status") == "active")
    return JSONResponse({
        "municipality": name,
        "asset_count": len(mun_assets),
        "active_assets": active,
        "event_count": len(mun_events),
        "asset_types": list({a.get("asset_type") for a in mun_assets if a.get("asset_type")}),
        "monitoring": _monitoring_readings_for_assets(mun_assets),
    })


class IncidentTransition(BaseModel):
    event_type: str
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class BootstrapRequest(BaseModel):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)


def _reading_dt(row: dict[str, Any]) -> datetime | None:
    return legacy._parse_dt(row.get("observed_date") or row.get("timestamp") or row.get("date") or row.get("time"))


def _resolve_vector(kind: str, metric: str | None) -> tuple[dict[str, Any], str]:
    vector = READING_VECTOR_REGISTRY.get(kind)
    if vector is None:
        raise HTTPException(status_code=400, detail={"error": "unknown_reading_kind", "kind": kind, "allowed": sorted(READING_VECTOR_REGISTRY)})
    metrics: dict[str, dict[str, Any]] = vector["metrics"]
    if metric is None:
        if vector["metric_required"]:
            raise HTTPException(status_code=400, detail={"error": "metric_required", "kind": kind, "allowed": sorted(metrics)})
        metric = next(iter(metrics))
    if metric not in metrics:
        raise HTTPException(status_code=400, detail={"error": "unknown_reading_metric", "kind": kind, "metric": metric, "allowed": sorted(metrics)})
    return vector, metric


def _series_rows(kind: str, metric: str) -> list[dict[str, Any]]:
    vector = READING_VECTOR_REGISTRY[kind]
    allowed_units = vector["metrics"][metric]["units"]
    return [row for row in legacy._load_jsonl(Path(vector["path"])) if row.get("metric") == metric and row.get("unit") in allowed_units]


def _all_incidents(series_keys: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Lifecycle incidents across the given ``(kind, metric)`` series."""
    incidents: list[dict[str, Any]] = []
    for kind, metric in series_keys:
        incidents.extend(lifecycle_alerts(kind, metric, _series_rows(kind, metric), legacy._parse_dt))
    return incidents


@app.get("/readings")
def readings(kind: str = Query(default="reservoir"), metric: str | None = Query(default=None), parameter_code: str | None = Query(default=None), site_no: str | None = Query(default=None), since: str | None = Query(default=None), until: str | None = Query(default=None)) -> JSONResponse:
    vector, metric = _resolve_vector(kind, metric)
    since_dt, until_dt = legacy._parse_dt(since), legacy._parse_dt(until)
    if since and since_dt is None:
        raise HTTPException(status_code=400, detail={"error": "invalid_since", "value": since})
    if until and until_dt is None:
        raise HTTPException(status_code=400, detail={"error": "invalid_until", "value": until})
    if since_dt and until_dt and since_dt > until_dt:
        raise HTTPException(status_code=400, detail={"error": "invalid_time_range"})
    rows = _series_rows(kind, metric)
    if parameter_code:
        rows = [row for row in rows if str(row.get("parameter_code") or "") == parameter_code]
    if site_no:
        rows = [row for row in rows if str(row.get("site_no") or "") == site_no]
    if since_dt or until_dt:
        rows = [row for row in rows if (observed := _reading_dt(row)) is not None and (not since_dt or observed >= since_dt) and (not until_dt or observed <= until_dt)]
    rows = sorted(rows, key=lambda row: (str(row.get("site_no") or ""), str(row.get("observed_date") or ""), str(row.get("parameter_code") or "")))
    units = sorted({str(row.get("unit")) for row in rows if row.get("unit") not in (None, "")})
    parameter_codes = sorted({str(row.get("parameter_code")) for row in rows if row.get("parameter_code") not in (None, "")})
    sites = Counter(str(row.get("site_no") or "unknown") for row in rows)
    return JSONResponse({"kind": kind, "metric": metric, "parameter_code": parameter_code, "site_no": site_no, "since": since, "until": until, "record_count": len(rows), "site_count": len(sites), "units": units, "parameter_codes": parameter_codes, "mixed_units": len(units) > 1, "provenance": series_policy(kind, metric), "quality": series_quality(kind, metric, rows, legacy._parse_dt), "items": rows})


@app.get("/monitoring/health")
def monitoring_health() -> JSONResponse:
    vectors = {}
    for (kind, metric), metadata in SERIES_METADATA_REGISTRY.items():
        rows = _series_rows(kind, metric)
        threshold = metadata["threshold"]
        # Key on kind:metric — a metric alone is no longer unique across corpora.
        vectors[f"{kind}:{metric}"] = {"kind": kind, "metric": metric, "record_count": len(rows), "quality": series_quality(kind, metric, rows, legacy._parse_dt), "threshold_provenance": threshold["provenance"] if threshold else None}
    events = read_events()
    chain_valid = True
    try:
        verify_chain(events)
    except ValueError:
        chain_valid = False
    return JSONResponse({"series_count": len(vectors), "vectors": vectors, "shadow_water_pipeline": True, "incident_ledger": {"event_count": len(events), "chain_valid": chain_valid, "notification_delivery_enabled": False}})


@app.get("/monitoring/alerts")
def monitoring_alerts(metric: str | None = Query(default=None), kind: str | None = Query(default=None), state: str = Query(default="active")) -> JSONResponse:
    # `metric` alone stays supported and now spans every corpus publishing it, so existing
    # callers keep working; `kind` narrows to one series when that matters.
    if metric and kind:
        keys = [(kind, metric)] if (kind, metric) in SERIES_METADATA_REGISTRY else []
    elif metric:
        keys = series_keys_for_metric(metric)
    elif kind:
        keys = [key for key in SERIES_METADATA_REGISTRY if key[0] == kind]
    else:
        keys = list(SERIES_METADATA_REGISTRY)
    if (metric or kind) and not keys:
        raise HTTPException(status_code=400, detail={"error": "unknown_reading_metric", "metric": metric, "kind": kind})
    if state not in {"active", "resolved", "all"}:
        raise HTTPException(status_code=400, detail={"error": "unknown_alert_state", "state": state})
    incidents = _all_incidents(keys)
    if state != "all":
        incidents = [item for item in incidents if item["state"] == state]
    return JSONResponse({"total": len(incidents), "state": state, "items": incidents})


@app.get("/monitoring/alert-operations")
def monitoring_alert_operations() -> JSONResponse:
    incidents = _all_incidents(list(SERIES_METADATA_REGISTRY))
    return JSONResponse({"incident_count": len(incidents), "active_count": sum(item["state"] == "active" for item in incidents), "resolved_count": sum(item["state"] == "resolved" for item in incidents), "deduplicated": True, "items": incidents})


@app.post("/monitoring/incidents/bootstrap", dependencies=[Depends(legacy._require_key)])
def bootstrap_incident_ledger(body: BootstrapRequest) -> JSONResponse:
    existing = materialized_state()
    created = []
    for incident in _all_incidents(list(SERIES_METADATA_REGISTRY)):
        if incident["incident_id"] in existing:
            continue
        created.append(append_event(incident["incident_id"], "opened", body.actor, body.reason, {
            "source": "phase2_materialization", "threshold_version": incident["dedup_key"], "evidence": incident,
        }))
    return JSONResponse({"created": len(created), "events": created})


@app.get("/monitoring/incidents")
def monitoring_incidents() -> JSONResponse:
    events = read_events()
    states = replay(events)
    return JSONResponse({
        "incident_count": len(states), "event_count": len(events), "append_only": True,
        "replay_equals_materialized_state": states == materialized_state(),
        "items": sorted(states.values(), key=lambda item: item["incident_id"]),
    })


@app.get("/monitoring/incidents/{incident_id}/timeline")
def monitoring_incident_timeline(incident_id: str) -> JSONResponse:
    items = timeline(incident_id)
    if not items:
        raise HTTPException(status_code=404, detail={"error": "incident_not_found", "incident_id": incident_id})
    return JSONResponse({"incident_id": incident_id, "event_count": len(items), "items": items})


@app.post("/monitoring/incidents/{incident_id}/transitions", dependencies=[Depends(legacy._require_key)])
def monitoring_incident_transition(incident_id: str, body: IncidentTransition) -> JSONResponse:
    if body.event_type not in ALLOWED_EVENTS - {"opened", "escalated"}:
        raise HTTPException(status_code=400, detail={"error": "unauthorized_transition_type", "event_type": body.event_type})
    states = materialized_state()
    if incident_id not in states:
        raise HTTPException(status_code=404, detail={"error": "incident_not_found", "incident_id": incident_id})
    event = append_event(incident_id, body.event_type, body.actor, body.reason, body.payload)
    return JSONResponse({"event": event, "state": materialized_state()[incident_id]})


@app.get("/monitoring/incidents/escalations/candidates")
def monitoring_escalation_candidates() -> JSONResponse:
    items = escalation_candidates(materialized_state())
    return JSONResponse({"total": len(items), "maintenance_aware": True, "items": items})


@app.get("/monitoring/incidents/notification-outbox")
def monitoring_notification_outbox() -> JSONResponse:
    return JSONResponse(notification_outbox(materialized_state()))


@app.get("/export/monitoring.json")
def export_monitoring() -> JSONResponse:
    series = []
    for (kind, metric), metadata in SERIES_METADATA_REGISTRY.items():
        rows = _series_rows(kind, metric)
        certified = [row for row in rows if not row.get("provisional")]
        series.append({"metric": metric, "kind": kind, "unit": metadata["unit"], "provenance": metadata, "quality": series_quality(kind, metric, rows, legacy._parse_dt), "certified_record_count": len(certified), "items": certified})
    return JSONResponse({"schema_version": "1.0.0", "series": series})


@app.get("/export/federation/monitoring-alerts.json")
def export_federation_monitoring_alerts() -> JSONResponse:
    return JSONResponse(federation_alert_export(_all_incidents(list(SERIES_METADATA_REGISTRY))))


@app.get("/export/federation/monitoring-incident-events.json")
def export_federation_monitoring_incident_events(cursor: str | None = Query(default=None)) -> JSONResponse:
    try:
        return JSONResponse(federation_delta(read_events(), cursor))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc), "cursor": cursor}) from exc
