"""Read-only cave and karst registry API for the AguaYLuz dashboard."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from aguayluz.cave_karst import (
    build_alerts,
    detect_status_contradictions,
    load_default_registry,
    materialize_status,
    validate_registry,
)

router = APIRouter(tags=["cave-karst"])

_SCOPE_STATEMENT = (
    "Río Camuy pilot registry only. This surface does not represent a complete "
    "Puerto Rico cave or karst census."
)
_STALE_AFTER_DAYS = 30
RULESET_VERSION = "KARST_ALERTS_1.1.0"

PILOT_STAGE_RISE_15M_M = 0.15
PILOT_STAGE_RISE_30M_M = 0.30
PILOT_RAIN_1H_MM = 25.0
PILOT_RAIN_3H_MM = 50.0
O2_DEFICIENT_PCT = 19.5
CO2_ELEVATED_PPM = 5_000.0
CO2_CRITICAL_PPM = 30_000.0
_RESTRICTED_PRIVACY = {"P2_CONTROLLED", "P3_RESTRICTED"}
_STATUS_EVENT_TYPES = {
    "status_transition",
    "status_observation",
    "closure_notice",
    "reopening_notice",
    "restriction_notice",
    "maintenance_update",
}
_OBSERVATION_PUBLIC_DENYLIST = {
    "sensor_id",
    "monitoring_site_id",
    "emergency_geometry",
    "evacuation_route",
    "muster_point",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load_registry() -> dict[str, list[dict[str, Any]]]:
    return load_default_registry()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _active_status_events(
    events: Iterable[dict[str, Any]], cutoff: datetime
) -> dict[str, list[dict[str, Any]]]:
    rows = [
        event
        for event in events
        if event.get("review_status") == "accepted"
        and event.get("event_type") in _STATUS_EVENT_TYPES
    ]
    superseded = {
        event["supersedes_event_id"]
        for event in rows
        if event.get("supersedes_event_id")
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in rows:
        if event.get("event_id") in superseded:
            continue
        effective = _parse_dt(event.get("effective_from")) or _parse_dt(
            event.get("observed_at")
        )
        effective_to = _parse_dt(event.get("effective_to"))
        if effective and effective <= cutoff and (not effective_to or cutoff <= effective_to):
            grouped[str(event.get("asset_id"))].append(event)
    return grouped


def _unresolved_tie_assets(
    events: Iterable[dict[str, Any]], cutoff: datetime
) -> set[str]:
    """Return assets whose highest-ranked current assertions are an unresolved tie."""
    tied: set[str] = set()
    distant_past = datetime.min.replace(tzinfo=timezone.utc)
    for asset_id, rows in _active_status_events(events, cutoff).items():
        ranked: list[tuple[tuple[datetime, datetime], dict[str, Any]]] = []
        for event in rows:
            effective = (
                _parse_dt(event.get("effective_from"))
                or _parse_dt(event.get("observed_at"))
                or distant_past
            )
            recorded = _parse_dt(event.get("recorded_at")) or distant_past
            ranked.append(((effective, recorded), event))
        if not ranked:
            continue
        max_rank = max(rank for rank, _ in ranked)
        winners = [event for rank, event in ranked if rank == max_rank]
        if len({str(event.get("to_status")) for event in winners}) > 1:
            tied.add(asset_id)
    return tied


def _materialize_v11_status(
    assets: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    *,
    as_of: datetime | None = None,
    stale_after_days: int = _STALE_AFTER_DAYS,
) -> list[dict[str, Any]]:
    """Materialize fail-closed v1.1/v1.2 state without mutating source records."""
    cutoff = as_of or _now_utc()
    event_rows = list(events)
    conflict_assets = {
        item["asset_id"] for item in detect_status_contradictions(event_rows)
    }
    conflict_assets.update(_unresolved_tie_assets(event_rows, cutoff))
    snapshots = materialize_status(assets, event_rows, as_of=cutoff)

    for snapshot in snapshots:
        operational = snapshot.setdefault("operational", {})
        asset_id = snapshot["asset_id"]
        if asset_id in conflict_assets:
            snapshot["current_status"] = "unknown"
            snapshot["status_quality"] = "conflicting"
            snapshot["conflict_hold"] = True
            operational["status_quality"] = "conflicting"
            operational["conflict_hold"] = True
            continue

        status_time = _parse_dt(snapshot.get("status_as_of"))
        stale = status_time is None or (cutoff - status_time).days > stale_after_days
        if stale:
            snapshot["current_status"] = "unknown"
            snapshot["status_quality"] = "stale"
            snapshot["conflict_hold"] = False
            operational["status_quality"] = "stale"
            operational["conflict_hold"] = False
        else:
            quality = operational.get("status_quality") or "verified"
            snapshot["status_quality"] = quality
            snapshot["conflict_hold"] = bool(operational.get("conflict_hold", False))
            if snapshot["conflict_hold"]:
                snapshot["current_status"] = "unknown"
                snapshot["status_quality"] = "conflicting"
    return snapshots


def _public_asset_projection(asset: dict[str, Any]) -> dict[str, Any]:
    """Return a server-side redacted public projection of one v1.1 asset."""
    payload = deepcopy(asset)
    privacy_class = str(payload.get("privacy_class") or "P3_RESTRICTED")
    disclosure = str(payload.get("location_disclosure") or "restricted")
    exact_public = privacy_class == "P0_PUBLIC" and disclosure == "public_exact"
    payload["coordinates_redacted"] = not exact_public
    if not exact_public:
        payload["lat"] = None
        payload["lon"] = None
        payload["geometry_crs"] = None
        payload["geometry_accuracy_m"] = None
        payload["geometry_source_ref"] = None

    legal = payload.get("legal") or {}
    culture = payload.get("culture") or {}
    monitoring = payload.get("monitoring") or {}
    emergency = payload.get("emergency") or {}
    legal["parcel_refs"] = []
    culture["heritage_registry_refs"] = []
    emergency["plan_ref"] = None
    emergency["evacuation_route_ref"] = None
    emergency["muster_point_ref"] = None
    monitoring["sensor_ids"] = []
    monitoring["site_ids"] = []

    if privacy_class in _RESTRICTED_PRIVACY:
        payload["canonical_name"] = (
            payload["canonical_name"]
            if privacy_class == "P2_CONTROLLED"
            else "Restricted cave/karst resource"
        )
        payload["aliases"] = []

    payload["legal"] = legal
    payload["culture"] = culture
    payload["monitoring"] = monitoring
    payload["emergency"] = emergency
    return payload


def _public_observation_projection(observation: dict[str, Any]) -> dict[str, Any]:
    """Strip controlled identifiers from one public observation projection."""
    return {
        key: deepcopy(value)
        for key, value in observation.items()
        if key not in _OBSERVATION_PUBLIC_DENYLIST
    }


def _validate_public_projection(asset: dict[str, Any]) -> list[str]:
    """Return privacy-policy diagnostics for a public asset payload."""
    errors: list[str] = []
    privacy_class = str(asset.get("privacy_class") or "P3_RESTRICTED")
    if privacy_class != "P0_PUBLIC" and (
        asset.get("lat") is not None or asset.get("lon") is not None
    ):
        errors.append("non-P0 asset exposes exact coordinates")
    if (asset.get("legal") or {}).get("parcel_refs"):
        errors.append("public payload exposes parcel_refs")
    if (asset.get("culture") or {}).get("heritage_registry_refs"):
        errors.append("public payload exposes heritage_registry_refs")
    emergency = asset.get("emergency") or {}
    if (
        emergency.get("plan_ref")
        or emergency.get("evacuation_route_ref")
        or emergency.get("muster_point_ref")
    ):
        errors.append("public payload exposes emergency references")
    monitoring = asset.get("monitoring") or {}
    if monitoring.get("sensor_ids") or monitoring.get("site_ids"):
        errors.append("public payload exposes controlled sensor identifiers")
    return errors


def _evaluate_replay_sample(sample: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate one normalized synthetic/pilot telemetry acceptance sample."""
    alerts: list[dict[str, Any]] = []

    def emit(alert_type: str, severity: int, action: str) -> None:
        alerts.append(
            {
                "alert_type": alert_type,
                "severity": severity,
                "action": action,
                "ruleset_version": RULESET_VERSION,
            }
        )

    stage_15 = sample.get("stage_rise_15m_m")
    stage_30 = sample.get("stage_rise_30m_m")
    rain_1h = sample.get("rain_1h_mm")
    rain_3h = sample.get("rain_3h_mm")
    o2 = sample.get("o2_pct")
    co2 = sample.get("co2_ppm")
    if sample.get("surveyed_evacuation_stage_exceeded") is True:
        emit("surveyed_evacuation_stage", 5, "close_and_evict")
    if (stage_15 is not None and float(stage_15) >= PILOT_STAGE_RISE_15M_M) or (
        stage_30 is not None and float(stage_30) >= PILOT_STAGE_RISE_30M_M
    ):
        emit("rapid_stage_rise", 4, "precautionary_close")
    if (rain_1h is not None and float(rain_1h) >= PILOT_RAIN_1H_MM) or (
        rain_3h is not None and float(rain_3h) >= PILOT_RAIN_3H_MM
    ):
        emit("intense_rainfall_precursor", 3, "hydrologic_watch")
    if o2 is not None and float(o2) < O2_DEFICIENT_PCT:
        emit("oxygen_deficiency", 5, "close_affected_zone")
    if co2 is not None and float(co2) >= CO2_CRITICAL_PPM:
        emit("critical_co2", 5, "evacuate_affected_zone")
    elif co2 is not None and float(co2) >= CO2_ELEVATED_PPM:
        emit("elevated_co2", 4, "restrict_and_review")
    if sample.get("critical_route_status") == "blocked":
        emit("emergency_route_blocked", 4, "close_dependent_zone")
    if sample.get("sensor_heartbeats_missed", 0) >= 2:
        emit("sensor_loss", 2, "mark_telemetry_degraded")
    if sample.get("comms_loss") is True:
        emit("communications_loss", 2, "mark_telemetry_degraded")
    if sample.get("calibration_overdue") is True:
        emit("sensor_calibration_overdue", 2, "mark_observations_provisional")
    return sorted(alerts, key=lambda item: (-item["severity"], item["alert_type"]))


# Compatibility aliases preserve the certified v1.1 import surface while the
# implementations remain internal helpers rather than independent GUI actions.
materialize_v11_status = _materialize_v11_status
public_asset_projection = _public_asset_projection
public_observation_projection = _public_observation_projection
validate_public_projection = _validate_public_projection
evaluate_replay_sample = _evaluate_replay_sample


def _validation_report(registry: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return validate_registry(
        registry["assets"],
        registry["sources"],
        registry["edges"],
        registry["events"],
        registry["observations"],
    )


def _require_valid_operational_registry(
    registry: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    report = _validation_report(registry)
    if not report["ok"]:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "cave_karst_registry_invalid",
                "operational_state": "unknown",
                "error_count": len(report["errors"]),
            },
        )
    return report


def _asset_or_404(
    registry: dict[str, list[dict[str, Any]]], asset_id: str
) -> dict[str, Any]:
    asset = next(
        (item for item in registry["assets"] if item.get("asset_id") == asset_id),
        None,
    )
    if asset is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "cave_karst_asset_not_found", "asset_id": asset_id},
        )
    return asset


def _freshness(status_as_of: str | None) -> dict[str, Any]:
    observed = _parse_dt(status_as_of)
    if observed is None:
        return {
            "status_as_of": status_as_of,
            "age_days": None,
            "stale": True,
            "stale_after_days": _STALE_AFTER_DAYS,
        }
    age_days = max(0, (_now_utc() - observed).days)
    return {
        "status_as_of": status_as_of,
        "age_days": age_days,
        "stale": age_days > _STALE_AFTER_DAYS,
        "stale_after_days": _STALE_AFTER_DAYS,
    }


def _unresolved_gaps(asset: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    operational = asset.get("operational") or {}
    hydrologic = asset.get("hydrologic") or {}
    environmental = asset.get("environmental") or {}
    infrastructure = asset.get("infrastructure") or {}
    if asset.get("review_status") != "accepted":
        gaps.append("record_requires_human_review")
    if not operational.get("status_as_of"):
        gaps.append("operational_status_date_unknown")
    if operational.get("status") in {"closed", "maintenance"} and not operational.get(
        "expected_reopen"
    ):
        gaps.append("reopening_date_unknown")
    if hydrologic.get("monitoring_status") in {None, "none", "unknown"}:
        gaps.append("hydrologic_monitoring_gap")
    if environmental.get("water_quality_monitoring") in {None, "none", "unknown"}:
        gaps.append("water_quality_monitoring_gap")
    if infrastructure.get("condition") in {None, "unknown"}:
        gaps.append("infrastructure_condition_unknown")
    if infrastructure.get("emergency_access") in {None, "unknown"}:
        gaps.append("emergency_access_status_unknown")
    return gaps


def _safe_alerts(registry: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    statuses = {
        item["asset_id"]: item["current_status"]
        for item in _materialize_v11_status(registry["assets"], registry["events"])
    }
    alerts = build_alerts(
        registry["assets"], registry["events"], stale_after_days=_STALE_AFTER_DAYS
    )
    return [
        alert
        for alert in alerts
        if alert.get("alert_type") != "hydrologic_access_risk"
        or statuses.get(str(alert.get("asset_id"))) in {"open", "partially_open"}
    ]


def _materialized_assets(
    registry: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    _require_valid_operational_registry(registry)
    alerts_by_asset: dict[str, list[dict[str, Any]]] = {}
    for alert in _safe_alerts(registry):
        alerts_by_asset.setdefault(str(alert["asset_id"]), []).append(alert)
    items: list[dict[str, Any]] = []
    for asset in _materialize_v11_status(registry["assets"], registry["events"]):
        payload = _public_asset_projection(asset)
        errors = _validate_public_projection(payload)
        if errors:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "cave_karst_public_projection_invalid",
                    "operational_state": "unknown",
                    "error_count": len(errors),
                },
            )
        payload["freshness"] = _freshness(payload.get("status_as_of"))
        payload["unresolved_gaps"] = _unresolved_gaps(payload)
        payload["active_alert_count"] = len(alerts_by_asset.get(payload["asset_id"], []))
        items.append(payload)
    return sorted(items, key=lambda item: (item["canonical_name"], item["asset_id"]))


def _related_edges(
    registry: dict[str, list[dict[str, Any]]], asset_id: str
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for edge in registry["edges"]:
        if edge.get("from_asset_id") == asset_id:
            items.append({**edge, "direction": "outbound"})
        elif edge.get("to_node_type") == "cave_asset" and edge.get("to_node_id") == asset_id:
            items.append({**edge, "direction": "inbound"})
    return sorted(items, key=lambda item: item["edge_id"])


def _related_sources(
    registry: dict[str, list[dict[str, Any]]], asset_id: str
) -> list[dict[str, Any]]:
    asset = _asset_or_404(registry, asset_id)
    source_ids = set(asset.get("source_refs") or [])
    for collection in ("events", "observations"):
        for item in registry[collection]:
            if item.get("asset_id") == asset_id and item.get("source_ref"):
                source_ids.add(item["source_ref"])
    for edge in _related_edges(registry, asset_id):
        source_ids.update(edge.get("source_refs") or [])
    return sorted(
        (item for item in registry["sources"] if item.get("source_id") in source_ids),
        key=lambda item: item["source_id"],
    )


def _statewide_complete(scopes: Counter[str], validation: dict[str, Any]) -> bool:
    """A valid scope literal is necessary but not sufficient for statewide completion."""
    return bool(scopes) and validation["ok"] and set(scopes) == {"statewide_validated"}


@router.get("/cave-karst/summary")
def cave_karst_summary() -> JSONResponse:
    registry = _load_registry()
    validation = _require_valid_operational_registry(registry)
    assets = _materialized_assets(registry)
    alerts = _safe_alerts(registry)
    scopes: Counter[str] = Counter(
        str(item.get("registry_scope") or "unknown") for item in assets
    )
    status_counts = Counter(str(item.get("current_status") or "unknown") for item in assets)
    review_counts = Counter(str(item.get("review_status") or "unknown") for item in assets)
    evidence_counts = Counter(str(item.get("evidence_tier") or "unknown") for item in assets)
    gap_count = sum(len(item["unresolved_gaps"]) for item in assets)
    return JSONResponse(
        {
            "scope": {
                "statement": _SCOPE_STATEMENT,
                "statewide_complete": _statewide_complete(scopes, validation),
                "registry_scope": dict(sorted(scopes.items())),
                "pilot_asset_id": "AYL_KARST_CAMUY_PARK",
            },
            "counts": {
                "assets": len(assets),
                "sources": len(registry["sources"]),
                "edges": len(registry["edges"]),
                "status_events": len(registry["events"]),
                "observations": len(registry["observations"]),
                "alerts": len(alerts),
                "unresolved_gaps": gap_count,
            },
            "status": dict(sorted(status_counts.items())),
            "review_status": dict(sorted(review_counts.items())),
            "evidence_tier": dict(sorted(evidence_counts.items())),
            "freshness": {
                "stale_assets": sum(bool(item["freshness"]["stale"]) for item in assets),
                "stale_after_days": _STALE_AFTER_DAYS,
            },
            "validation": {
                "ok": validation["ok"],
                "error_count": len(validation["errors"]),
                "contradiction_count": validation["contradiction_count"],
            },
        }
    )


@router.get("/cave-karst/assets")
def cave_karst_assets(
    status: str | None = Query(default=None),
    asset_kind: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
) -> JSONResponse:
    registry = _load_registry()
    items = _materialized_assets(registry)
    if status:
        items = [item for item in items if item.get("current_status") == status]
    if asset_kind:
        items = [item for item in items if item.get("asset_kind") == asset_kind]
    if review_status:
        items = [item for item in items if item.get("review_status") == review_status]
    return JSONResponse({"total": len(items), "items": items})


@router.get("/cave-karst/assets/{asset_id}")
def cave_karst_asset(asset_id: str) -> JSONResponse:
    registry = _load_registry()
    _require_valid_operational_registry(registry)
    _asset_or_404(registry, asset_id)
    asset = next(
        item for item in _materialized_assets(registry) if item["asset_id"] == asset_id
    )
    asset["observations"] = sorted(
        (
            _public_observation_projection(item)
            for item in registry["observations"]
            if item.get("asset_id") == asset_id
        ),
        key=lambda item: (str(item.get("observed_at") or ""), item["observation_id"]),
        reverse=True,
    )
    asset["alerts"] = [
        item for item in _safe_alerts(registry) if item.get("asset_id") == asset_id
    ]
    asset["edge_count"] = len(_related_edges(registry, asset_id))
    asset["source_count"] = len(_related_sources(registry, asset_id))
    return JSONResponse(asset)


@router.get("/cave-karst/assets/{asset_id}/status-history")
def cave_karst_status_history(asset_id: str) -> JSONResponse:
    registry = _load_registry()
    _asset_or_404(registry, asset_id)
    items = sorted(
        (item for item in registry["events"] if item.get("asset_id") == asset_id),
        key=lambda item: (
            str(item.get("effective_from") or item.get("observed_at") or ""),
            str(item.get("recorded_at") or ""),
            item["event_id"],
        ),
        reverse=True,
    )
    return JSONResponse({"asset_id": asset_id, "total": len(items), "items": items})


@router.get("/cave-karst/assets/{asset_id}/provenance")
def cave_karst_provenance(asset_id: str) -> JSONResponse:
    registry = _load_registry()
    sources = _related_sources(registry, asset_id)
    return JSONResponse(
        {
            "asset_id": asset_id,
            "total": len(sources),
            "items": sources,
            "evidence_policy": (
                "Sources are shown as recorded. Current operational claims remain "
                "bounded by review status, evidence tier, supersession history, "
                "registry validation, freshness, and conflict holds."
            ),
        }
    )


@router.get("/cave-karst/assets/{asset_id}/edges")
def cave_karst_edges(asset_id: str) -> JSONResponse:
    registry = _load_registry()
    _asset_or_404(registry, asset_id)
    items = _related_edges(registry, asset_id)
    return JSONResponse({"asset_id": asset_id, "total": len(items), "items": items})


@router.get("/cave-karst/alerts")
def cave_karst_alerts(
    severity_min: int = Query(default=1, ge=1, le=5),
    alert_type: str | None = Query(default=None),
) -> JSONResponse:
    registry = _load_registry()
    _require_valid_operational_registry(registry)
    items = [
        item
        for item in _safe_alerts(registry)
        if int(item.get("severity") or 0) >= severity_min
    ]
    if alert_type:
        items = [item for item in items if item.get("alert_type") == alert_type]
    return JSONResponse({"total": len(items), "items": items})
