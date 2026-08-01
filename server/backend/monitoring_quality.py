"""Monitoring quality, freshness, provenance, and native alert policies."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SERIES_METADATA_REGISTRY: dict[str, dict[str, Any]] = {
    "reservoir_elevation": {
        "kind": "reservoir", "unit": "ft", "parameter_codes": ["62615", "00065"],
        "datum_required": True, "freshness_hours": 48,
        "threshold": {"direction": "below", "value": 20.0, "severity": 3, "provenance": "operator_policy_v1"},
    },
    "reservoir_storage_pct": {
        "kind": "reservoir", "unit": "%", "parameter_codes": ["00054"],
        "datum_required": False, "freshness_hours": 48,
        "threshold": {"direction": "below", "value": 30.0, "severity": 4, "provenance": "operator_policy_v1"},
    },
    "streamflow": {
        "kind": "reservoir", "unit": "ft3/s", "parameter_codes": ["00060"],
        "datum_required": False, "freshness_hours": 24,
        "threshold": {"direction": "above", "value": 5000.0, "severity": 4, "provenance": "operator_policy_v1"},
    },
    "gage_height": {
        "kind": "reservoir", "unit": "ft", "parameter_codes": ["00065"],
        "datum_required": True, "freshness_hours": 24,
        "threshold": {"direction": "above", "value": 15.0, "severity": 4, "provenance": "operator_policy_v1"},
    },
    "groundwater_level": {
        "kind": "groundwater", "unit": "ft", "parameter_codes": ["72019"],
        "datum_required": True, "freshness_hours": 72,
        "threshold": {"direction": "above", "value": 50.0, "severity": 3, "provenance": "operator_policy_v1"},
    },
    "coastal_water_level": {
        "kind": "coastal", "unit": "ft", "parameter_codes": ["8665530"],
        "datum_required": True, "freshness_hours": 6,
        "threshold": {"direction": "above", "value": 4.0, "severity": 4, "provenance": "operator_policy_v1"},
    },
}


def observation_time(row: dict[str, Any], parse_dt) -> datetime | None:
    return parse_dt(row.get("observed_date") or row.get("timestamp") or row.get("date") or row.get("time"))


def series_quality(metric: str, rows: list[dict[str, Any]], parse_dt, now: datetime | None = None) -> dict[str, Any]:
    policy = SERIES_METADATA_REGISTRY[metric]
    now = now or datetime.now(timezone.utc)
    observed = [dt for row in rows if (dt := observation_time(row, parse_dt))]
    latest = max(observed) if observed else None
    age_hours = round((now - latest).total_seconds() / 3600, 2) if latest else None
    freshness = "unknown" if age_hours is None else ("fresh" if age_hours <= policy["freshness_hours"] else "stale")
    provisional_count = sum(bool(row.get("provisional")) for row in rows)
    datum_values = sorted({str(row.get("datum")) for row in rows if row.get("datum")})
    datum_status = "declared" if datum_values else ("missing" if policy["datum_required"] else "not_required")
    certified_count = sum(not bool(row.get("provisional")) for row in rows)
    return {
        "latest_observed_at": latest.isoformat() if latest else None,
        "age_hours": age_hours,
        "freshness": freshness,
        "freshness_limit_hours": policy["freshness_hours"],
        "provisional_count": provisional_count,
        "certified_count": certified_count,
        "datum_status": datum_status,
        "datums": datum_values,
        "ingest_health": "healthy" if rows and freshness == "fresh" else ("stale" if rows else "empty"),
    }


def native_alerts(metric: str, rows: list[dict[str, Any]], parse_dt) -> list[dict[str, Any]]:
    policy = SERIES_METADATA_REGISTRY[metric]
    threshold = policy["threshold"]
    if not threshold.get("provenance"):
        raise ValueError(f"threshold_without_provenance:{metric}")
    alerts: list[dict[str, Any]] = []
    for row in rows:
        if row.get("provisional"):
            continue
        value = row.get("value")
        if not isinstance(value, (int, float)):
            continue
        tripped = value > threshold["value"] if threshold["direction"] == "above" else value < threshold["value"]
        if not tripped:
            continue
        observed = observation_time(row, parse_dt)
        alerts.append({
            "alert_id": f"MON-{metric}-{row.get('site_no', 'unknown')}-{row.get('observed_date', 'unknown')}",
            "metric": metric,
            "site_no": row.get("site_no"),
            "observed_at": observed.isoformat() if observed else None,
            "value": value,
            "unit": row.get("unit"),
            "severity": threshold["severity"],
            "threshold": threshold,
            "certification": "certified",
        })
    return alerts
