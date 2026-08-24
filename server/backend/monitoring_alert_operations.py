"""Site-threshold resolution and deterministic monitoring alert lifecycle."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from server.backend.monitoring_quality import observation_time, series_policy

SITE_THRESHOLD_CONFIG = Path(__file__).resolve().parents[2] / "config" / "monitoring_site_thresholds.json"


def load_site_thresholds(path: Path = SITE_THRESHOLD_CONFIG) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "1.0.0", "policy": {}, "site_thresholds": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("site_thresholds"), dict):
        raise ValueError("invalid_site_threshold_registry")
    return payload


def resolve_threshold(
    kind: str, metric: str, site_no: str | None, registry: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Effective threshold for a series, or ``None`` for a reference series.

    Site overrides stay keyed by *metric* in config/monitoring_site_thresholds.json — a
    threshold is a property of the measured quantity at a site, not of which corpus
    published it, and that file is currently empty so nothing needed migrating.
    """
    metadata = series_policy(kind, metric)
    if metadata["threshold"] is None:
        return None
    threshold = dict(metadata["threshold"])
    threshold.update({"scope": "default", "site_no": None, "effective_date": None})
    registry = registry or load_site_thresholds()
    site_key = str(site_no or "unknown")
    override = registry.get("site_thresholds", {}).get(metric, {}).get(site_key)
    if override is None:
        return threshold
    if not override.get("provenance"):
        raise ValueError(f"site_threshold_without_provenance:{metric}:{site_key}")
    if not override.get("effective_date"):
        raise ValueError(f"site_threshold_without_effective_date:{metric}:{site_key}")
    threshold.update(override)
    threshold.update({"scope": "site", "site_no": site_key})
    return threshold


def threshold_tripped(value: float, threshold: dict[str, Any]) -> bool:
    return value > threshold["value"] if threshold["direction"] == "above" else value < threshold["value"]


def _incident_id(metric: str, site_no: str, threshold: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "metric": metric,
            "site_no": site_no,
            "direction": threshold["direction"],
            "value": threshold["value"],
            "provenance": threshold["provenance"],
            "effective_date": threshold.get("effective_date"),
        },
        sort_keys=True,
    )
    return f"MON-{hashlib.sha256(material.encode()).hexdigest()[:20]}"


def lifecycle_alerts(
    kind: str,
    metric: str,
    rows: list[dict[str, Any]],
    parse_dt,
    registry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return one deduplicated lifecycle incident per exact metric/site."""
    if series_policy(kind, metric)["threshold"] is None:
        # Reference series (historical peaks, discrete well visits): inspectable, never an
        # alerting surface. Checked once here rather than per site — a series without a
        # default threshold has none for any site either.
        return []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("provisional") or not isinstance(row.get("value"), (int, float)):
            continue
        grouped[str(row.get("site_no") or "unknown")].append(row)

    incidents: list[dict[str, Any]] = []
    for site_no, site_rows in sorted(grouped.items()):
        ordered = sorted(
            site_rows,
            key=lambda row: observation_time(row, parse_dt) or parse_dt("1970-01-01T00:00:00Z"),
        )
        threshold = resolve_threshold(kind, metric, site_no, registry)
        assert threshold is not None      # guarded above; narrows the type for mypy
        breaches = [row for row in ordered if threshold_tripped(float(row["value"]), threshold)]
        if not breaches:
            continue
        latest = ordered[-1]
        latest_dt = observation_time(latest, parse_dt)
        first_breach_dt = observation_time(breaches[0], parse_dt)
        last_breach_dt = observation_time(breaches[-1], parse_dt)
        active = threshold_tripped(float(latest["value"]), threshold)
        incidents.append({
            "incident_id": _incident_id(metric, site_no, threshold),
            "metric": metric,
            "site_no": site_no,
            "state": "active" if active else "resolved",
            "severity": threshold["severity"],
            "threshold": threshold,
            "first_breached_at": first_breach_dt.isoformat() if first_breach_dt else None,
            "last_breached_at": last_breach_dt.isoformat() if last_breach_dt else None,
            "latest_observed_at": latest_dt.isoformat() if latest_dt else None,
            "latest_value": latest["value"],
            "unit": latest.get("unit"),
            "evidence_count": len(breaches),
            "certification": "certified",
            "dedup_key": f"{metric}:{site_no}:{threshold['provenance']}:{threshold.get('effective_date')}",
        })
    return incidents


def federation_alert_export(incidents: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce a stable federation envelope for current alert incidents."""
    active = sum(item["state"] == "active" for item in incidents)
    resolved = sum(item["state"] == "resolved" for item in incidents)
    return {
        "schema_version": "1.0.0",
        "contract": "aguayluz.monitoring.alert-incidents",
        "certification": "certified-only",
        "incident_count": len(incidents),
        "active_count": active,
        "resolved_count": resolved,
        "items": incidents,
    }
