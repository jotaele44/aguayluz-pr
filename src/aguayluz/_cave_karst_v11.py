"""Cave & Karst Monitor v1.1 policy and acceptance primitives.

This module is additive over :mod:`aguayluz.cave_karst`. It keeps the existing
append-only event/hash implementation intact while adding fail-closed public
materialization, privacy projection, and deterministic Río Camuy replay rules.
"""
from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .cave_karst import detect_status_contradictions, materialize_status

RULESET_VERSION = "KARST_ALERTS_1.1.0"
STALE_AFTER_DAYS = 30

# Pilot engineering thresholds. These are acceptance-fixture defaults, not
# Puerto Rico regulatory standards or final Río Camuy operating thresholds.
PILOT_STAGE_RISE_15M_M = 0.15
PILOT_STAGE_RISE_30M_M = 0.30
PILOT_RAIN_1H_MM = 25.0
PILOT_RAIN_3H_MM = 50.0
O2_DEFICIENT_PCT = 19.5
CO2_ELEVATED_PPM = 5_000.0
CO2_CRITICAL_PPM = 30_000.0

_RESTRICTED_PRIVACY = {"P2_CONTROLLED", "P3_RESTRICTED"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def materialize_v11_status(
    assets: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    *,
    as_of: datetime | None = None,
    stale_after_days: int = STALE_AFTER_DAYS,
) -> list[dict[str, Any]]:
    """Materialize fail-closed v1.1 state without mutating source records.

    Contradictory accepted status evidence cannot project an ``open`` state.
    Stale evidence projects ``unknown`` rather than silently preserving access.
    """
    cutoff = as_of or datetime.now(timezone.utc)
    event_rows = list(events)
    conflict_assets = {
        item["asset_id"] for item in detect_status_contradictions(event_rows)
    }
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
    return snapshots


def public_asset_projection(asset: dict[str, Any]) -> dict[str, Any]:
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

    # Sensitive fields never reach the public payload, regardless of frontend.
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


def validate_public_projection(asset: dict[str, Any]) -> list[str]:
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
    if emergency.get("evacuation_route_ref") or emergency.get("muster_point_ref"):
        errors.append("public payload exposes emergency geometry references")
    monitoring = asset.get("monitoring") or {}
    if monitoring.get("sensor_ids") or monitoring.get("site_ids"):
        errors.append("public payload exposes controlled sensor identifiers")
    return errors


def evaluate_replay_sample(sample: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate one normalized synthetic/pilot telemetry sample.

    The function only emits deterministic acceptance-test alerts. Final field
    thresholds remain site-calibration and operator-approval dependent.
    """
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
    if sample.get("calibration_overdue") is True:
        emit("sensor_calibration_overdue", 2, "mark_observations_provisional")

    return sorted(alerts, key=lambda item: (-item["severity"], item["alert_type"]))
