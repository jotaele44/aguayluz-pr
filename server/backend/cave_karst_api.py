"""Read-only cave and karst registry API for the AguaYLuz dashboard."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from aguayluz.cave_karst import (
    build_alerts,
    load_default_registry,
    materialize_status,
    validate_registry,
)

router = APIRouter(prefix="/cave-karst", tags=["cave-karst"])

_SCOPE_STATEMENT = (
    "Río Camuy pilot registry only. This surface does not represent a complete "
    "Puerto Rico cave or karst census."
)
_STALE_AFTER_DAYS = 30


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


def _redact_coordinates(asset: dict[str, Any]) -> dict[str, Any]:
    payload = dict(asset)
    disclosure = str(asset.get("location_disclosure") or "nonpublic")
    payload["coordinates_redacted"] = disclosure != "public_exact"
    if disclosure != "public_exact":
        payload["lat"] = None
        payload["lon"] = None
    return payload


def _freshness(status_as_of: str | None) -> dict[str, Any]:
    observed = _parse_dt(status_as_of)
    if observed is None:
        return {
            "status_as_of": status_as_of,
            "age_days": None,
            "stale": True,
            "stale_after_days": _STALE_AFTER_DAYS,
        }
    age_days = max(0, (datetime.now(timezone.utc) - observed).days)
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


def _materialized_assets(
    registry: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    alerts_by_asset: dict[str, list[dict[str, Any]]] = {}
    for alert in build_alerts(
        registry["assets"],
        registry["events"],
        stale_after_days=_STALE_AFTER_DAYS,
    ):
        alerts_by_asset.setdefault(str(alert["asset_id"]), []).append(alert)

    items: list[dict[str, Any]] = []
    for asset in materialize_status(registry["assets"], registry["events"]):
        payload = _redact_coordinates(asset)
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


@router.get("/summary")
def cave_karst_summary() -> JSONResponse:
    registry = _load_registry()
    assets = _materialized_assets(registry)
    validation = validate_registry(
        registry["assets"],
        registry["sources"],
        registry["edges"],
        registry["events"],
        registry["observations"],
    )
    alerts = build_alerts(
        registry["assets"],
        registry["events"],
        stale_after_days=_STALE_AFTER_DAYS,
    )
    scopes = Counter(str(item.get("registry_scope") or "unknown") for item in assets)
    status_counts = Counter(str(item.get("current_status") or "unknown") for item in assets)
    review_counts = Counter(str(item.get("review_status") or "unknown") for item in assets)
    evidence_counts = Counter(str(item.get("evidence_tier") or "unknown") for item in assets)
    gap_count = sum(len(item["unresolved_gaps"]) for item in assets)

    return JSONResponse(
        {
            "scope": {
                "statement": _SCOPE_STATEMENT,
                "statewide_complete": bool(assets) and set(scopes) == {"statewide"},
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


@router.get("/assets")
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


@router.get("/assets/{asset_id}")
def cave_karst_asset(asset_id: str) -> JSONResponse:
    registry = _load_registry()
    _asset_or_404(registry, asset_id)
    asset = next(
        item for item in _materialized_assets(registry) if item["asset_id"] == asset_id
    )
    asset["observations"] = sorted(
        (
            item
            for item in registry["observations"]
            if item.get("asset_id") == asset_id
        ),
        key=lambda item: (str(item.get("observed_at") or ""), item["observation_id"]),
        reverse=True,
    )
    asset["alerts"] = [
        item
        for item in build_alerts(
            registry["assets"],
            registry["events"],
            stale_after_days=_STALE_AFTER_DAYS,
        )
        if item.get("asset_id") == asset_id
    ]
    asset["edge_count"] = len(_related_edges(registry, asset_id))
    asset["source_count"] = len(_related_sources(registry, asset_id))
    return JSONResponse(asset)


@router.get("/assets/{asset_id}/status-history")
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


@router.get("/assets/{asset_id}/provenance")
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
                "bounded by review status, evidence tier, and supersession history."
            ),
        }
    )


@router.get("/assets/{asset_id}/edges")
def cave_karst_edges(asset_id: str) -> JSONResponse:
    registry = _load_registry()
    _asset_or_404(registry, asset_id)
    items = _related_edges(registry, asset_id)
    return JSONResponse({"asset_id": asset_id, "total": len(items), "items": items})


@router.get("/alerts")
def cave_karst_alerts(
    severity_min: int = Query(default=1, ge=1, le=5),
    alert_type: str | None = Query(default=None),
) -> JSONResponse:
    registry = _load_registry()
    items = [
        item
        for item in build_alerts(
            registry["assets"],
            registry["events"],
            stale_after_days=_STALE_AFTER_DAYS,
        )
        if int(item.get("severity") or 0) >= severity_min
    ]
    if alert_type:
        items = [item for item in items if item.get("alert_type") == alert_type]
    return JSONResponse({"total": len(items), "items": items})
