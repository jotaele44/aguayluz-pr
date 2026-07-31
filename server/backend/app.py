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
from server.backend.monitoring_quality import SERIES_METADATA_REGISTRY, series_quality
from server.backend.water_disruption_api import router as water_disruption_router


def _is_legacy_readings(route: Any) -> bool:
    return getattr(route, "path", None) == "/readings" and "GET" in getattr(route, "methods", set())


app = FastAPI(title=legacy.app.title)
app.router.routes.extend(route for route in legacy.app.router.routes if not _is_legacy_readings(route))
app.exception_handlers.update(legacy.app.exception_handlers)
app.dependency_overrides.update(legacy.app.dependency_overrides)
for middleware in reversed(legacy.app.user_middleware):
    app.add_middleware(middleware.cls, *middleware.args, **middleware.kwargs)
app.include_router(water_disruption_router)

READING_VECTOR_REGISTRY: dict[str, dict[str, Any]] = {
    "reservoir": {"path": legacy.DATA / "reservoir_levels.jsonl", "metrics": {"reservoir_elevation": {"units": {"ft"}}, "reservoir_storage_pct": {"units": {"%"}}, "streamflow": {"units": {"ft3/s", "ft³/s"}}, "gage_height": {"units": {"ft"}}}, "metric_required": True},
    "groundwater": {"path": legacy.DATA / "groundwater_levels.jsonl", "metrics": {"groundwater_level": {"units": {"ft"}}}, "metric_required": False},
    "coastal": {"path": legacy.DATA / "coastal_levels.jsonl", "metrics": {"coastal_water_level": {"units": {"ft"}}}, "metric_required": False},
}


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


def _all_incidents(metrics: list[str]) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    for metric in metrics:
        metadata = SERIES_METADATA_REGISTRY[metric]
        incidents.extend(lifecycle_alerts(metric, _series_rows(metadata["kind"], metric), legacy._parse_dt))
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
    return JSONResponse({"kind": kind, "metric": metric, "parameter_code": parameter_code, "site_no": site_no, "since": since, "until": until, "record_count": len(rows), "site_count": len(sites), "units": units, "parameter_codes": parameter_codes, "mixed_units": len(units) > 1, "provenance": SERIES_METADATA_REGISTRY[metric], "quality": series_quality(metric, rows, legacy._parse_dt), "items": rows})


@app.get("/monitoring/health")
def monitoring_health() -> JSONResponse:
    vectors = {}
    for metric, metadata in SERIES_METADATA_REGISTRY.items():
        rows = _series_rows(metadata["kind"], metric)
        vectors[metric] = {"kind": metadata["kind"], "record_count": len(rows), "quality": series_quality(metric, rows, legacy._parse_dt), "threshold_provenance": metadata["threshold"]["provenance"]}
    events = read_events()
    chain_valid = True
    try:
        verify_chain(events)
    except ValueError:
        chain_valid = False
    return JSONResponse({"series_count": len(vectors), "vectors": vectors, "shadow_water_pipeline": True, "incident_ledger": {"event_count": len(events), "chain_valid": chain_valid, "notification_delivery_enabled": False}})


@app.get("/monitoring/alerts")
def monitoring_alerts(metric: str | None = Query(default=None), state: str = Query(default="active")) -> JSONResponse:
    metrics = [metric] if metric else list(SERIES_METADATA_REGISTRY)
    unknown = [name for name in metrics if name not in SERIES_METADATA_REGISTRY]
    if unknown:
        raise HTTPException(status_code=400, detail={"error": "unknown_reading_metric", "metric": unknown[0]})
    if state not in {"active", "resolved", "all"}:
        raise HTTPException(status_code=400, detail={"error": "unknown_alert_state", "state": state})
    incidents = _all_incidents(metrics)
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
    for metric, metadata in SERIES_METADATA_REGISTRY.items():
        rows = _series_rows(metadata["kind"], metric)
        certified = [row for row in rows if not row.get("provisional")]
        series.append({"metric": metric, "kind": metadata["kind"], "unit": metadata["unit"], "provenance": metadata, "quality": series_quality(metric, rows, legacy._parse_dt), "certified_record_count": len(certified), "items": certified})
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
