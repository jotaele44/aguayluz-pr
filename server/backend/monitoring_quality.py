"""Monitoring quality, freshness, provenance, and native alert policies.

Keyed on ``(kind, metric)``, NOT on metric alone.

The one-entry-per-metric shape this replaced encoded an assumption that a metric belongs to
exactly one corpus, and that stopped being true once discrete USGS field measurements and
annual peak flow arrived: they legitimately reuse ``groundwater_level``, ``streamflow`` and
``gage_height``, which the daily-values vectors already claimed. Under the old shape
``/readings?kind=usgs_peaks&metric=streamflow`` answered 200 while reporting the
*reservoir* policy — 46% of the 1899-2025 peak record breached a threshold written for live
reservoir discharge, and the whole series read "stale" against a 24-hour limit. Every
metric-iterating endpoint also resolved ``metadata["kind"]`` and so never saw the new files
at all.

Two fields are deliberately nullable:

* ``threshold: None`` marks a **reference series** — one that exists to be inspected and to
  give historical context, not to alert. An annual peak *is* the record; there is no
  operational threshold to breach. ``native_alerts`` and ``resolve_threshold`` return
  nothing for these rather than raising.
* ``freshness_hours: None`` marks a series for which staleness is not a meaningful
  question. The newest annual peak being from water year 2025 is correct, not degraded.

Note on ``datum``: ``series_quality`` reads ``row.get("datum")``, but
``schemas/monitoring_reading.schema.json`` sets ``additionalProperties: false`` and has no
``datum`` property, so no schema-valid reading can carry one and ``datum_status`` is
permanently ``"missing"`` for every ``datum_required`` series. That is a known dead branch,
pinned by ``tests/test_monitoring_phase1.py``. Do not "fix" it by adding the field —
``federation_export.py`` validates every exported row and the extra key would fail G01.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

#: ``(kind, metric)`` -> policy. See the module docstring for why the key is a pair.
SERIES_METADATA_REGISTRY: dict[tuple[str, str], dict[str, Any]] = {
    ("reservoir", "reservoir_elevation"): {
        "kind": "reservoir", "unit": "ft", "parameter_codes": ["62615", "00065"],
        "datum_required": True, "freshness_hours": 48,
        "threshold": {"direction": "below", "value": 20.0, "severity": 3, "provenance": "operator_policy_v1"},
    },
    ("reservoir", "reservoir_storage_pct"): {
        "kind": "reservoir", "unit": "%", "parameter_codes": ["00054"],
        "datum_required": False, "freshness_hours": 48,
        "threshold": {"direction": "below", "value": 30.0, "severity": 4, "provenance": "operator_policy_v1"},
    },
    ("reservoir", "streamflow"): {
        "kind": "reservoir", "unit": "ft3/s", "parameter_codes": ["00060"],
        "datum_required": False, "freshness_hours": 24,
        "threshold": {"direction": "above", "value": 5000.0, "severity": 4, "provenance": "operator_policy_v1"},
    },
    ("reservoir", "gage_height"): {
        "kind": "reservoir", "unit": "ft", "parameter_codes": ["00065"],
        "datum_required": True, "freshness_hours": 24,
        "threshold": {"direction": "above", "value": 15.0, "severity": 4, "provenance": "operator_policy_v1"},
    },
    ("groundwater", "groundwater_level"): {
        "kind": "groundwater", "unit": "ft", "parameter_codes": ["72019"],
        "datum_required": True, "freshness_hours": 72,
        "threshold": {"direction": "above", "value": 50.0, "severity": 3, "provenance": "operator_policy_v1"},
    },
    ("coastal", "coastal_water_level"): {
        "kind": "coastal", "unit": "ft", "parameter_codes": ["8665530"],
        "datum_required": True, "freshness_hours": 6,
        "threshold": {"direction": "above", "value": 4.0, "severity": 4, "provenance": "operator_policy_v1"},
    },
    # ── reference series: inspectable, never alerting ──────────────────────────
    ("usgs_field_measurements", "groundwater_level"): {
        # Discrete hydrographer visits, which the Daily Values ingest structurally cannot
        # see. 90 days because a well is typically read a few times a year — the 72-hour
        # limit the continuous vector uses would mark a healthy feed stale within a week.
        "kind": "usgs_field_measurements", "unit": "ft", "parameter_codes": ["72019", "62610"],
        "datum_required": True, "freshness_hours": 2160,
        # No threshold: 89 wells with no per-site baselines, and 62610 (level above datum)
        # runs opposite to 72019 (depth below surface), so one number cannot mean
        # "drawdown" for both. Per-site policy would go in
        # config/monitoring_site_thresholds.json once baselines exist.
        "threshold": None,
    },
    ("usgs_peaks", "streamflow"): {
        "kind": "usgs_peaks", "unit": "ft^3/s", "parameter_codes": ["00060"],
        "datum_required": False, "freshness_hours": None,
        # An annual peak IS the historical record, so there is nothing to breach: the
        # reservoir threshold (>5,000 ft3/s) is exceeded by 46% of the 1899-2025 record.
        "threshold": None,
    },
    ("usgs_peaks", "gage_height"): {
        "kind": "usgs_peaks", "unit": "ft", "parameter_codes": ["00065"],
        "datum_required": True, "freshness_hours": None,
        "threshold": None,
    },
    # NEON (docs/NEON_INTEGRATION.md): a research-observatory feed, not an operational one —
    # no operator threshold exists for it. Its constituent products also publish on
    # genuinely mixed cadences (continuous sensors alongside irregular field campaigns; see
    # aguayluz.neon.mapping.IRREGULAR_CADENCE_PRODUCTS), so a single freshness SLA would be
    # invented rather than derived from anything real. Treated as a reference series, like
    # usgs_peaks above.
    ("neon", "streamflow"): {
        "kind": "neon", "unit": "m3/s",
        "parameter_codes": ["DP4.00130.001", "DP1.20193.001", "DP1.20048.001"],
        "datum_required": False, "freshness_hours": None,
        "threshold": None,
    },
    ("neon", "gage_height"): {
        "kind": "neon", "unit": "m", "parameter_codes": ["DP1.20016.001"],
        "datum_required": True, "freshness_hours": None,
        "threshold": None,
    },
    # `drought` and `precipitation` were missing from this registry entirely — every
    # /readings request for either kind unconditionally called series_policy() below and
    # raised KeyError, which FastAPI turns into a connection-level failure rather than a
    # clean error body. Latent since 42d5d2b (2026-08-07): dashboard/src/lib/monitoring.js
    # has always advertised drought_category and both precipitation series as selectable
    # in MonitoringCharts.jsx, but nothing surfaced this until scripts/ingest_drought_usdm.py
    # / ingest_precip_ncei.py were actually run and something queried the readings for them.
    ("drought", "drought_category"): {
        "kind": "drought", "unit": "category", "parameter_codes": ["D0", "D1", "D2", "D3", "D4", "None"],
        # USDM publishes weekly; 10 days covers a missed release without false "stale".
        "datum_required": False, "freshness_hours": 24 * 10,
        # Official NDMC/USDM classification, "not a derived proxy" per monitoring.js's own
        # note on this series — no operator-set threshold exists for it.
        "threshold": None,
    },
    ("precipitation", "precipitation_pct_normal"): {
        "kind": "precipitation", "unit": "%", "parameter_codes": ["30d", "90d"],
        # Rolling 30/90-day comparison against a climatological normal, not a live feed —
        # generous slack over NCEI's typical publication cadence.
        "datum_required": False, "freshness_hours": 24 * 35,
        # "A corroborating signal for the drought classification above, not an official
        # index" per monitoring.js's own note — no operator threshold.
        "threshold": None,
    },
}


def series_policy(kind: str, metric: str) -> dict[str, Any]:
    """Policy for one ``(kind, metric)`` series.

    The single accessor, so a caller cannot accidentally reintroduce the metric-only
    lookup this registry was re-keyed to eliminate.
    """
    try:
        return SERIES_METADATA_REGISTRY[(kind, metric)]
    except KeyError:
        raise KeyError(f"unregistered_series:{kind}:{metric}") from None


def series_keys_for_metric(metric: str) -> list[tuple[str, str]]:
    """Every ``(kind, metric)`` series carrying this metric, in registry order."""
    return [key for key in SERIES_METADATA_REGISTRY if key[1] == metric]


def observation_time(row: dict[str, Any], parse_dt) -> datetime | None:
    return parse_dt(row.get("observed_date") or row.get("timestamp") or row.get("date") or row.get("time"))


def series_quality(
    kind: str, metric: str, rows: list[dict[str, Any]], parse_dt, now: datetime | None = None
) -> dict[str, Any]:
    policy = series_policy(kind, metric)
    limit = policy["freshness_hours"]
    now = now or datetime.now(timezone.utc)
    observed = [dt for row in rows if (dt := observation_time(row, parse_dt))]
    latest = max(observed) if observed else None
    age_hours = round((now - latest).total_seconds() / 3600, 2) if latest else None
    if limit is None:
        # A historical reference series is never "stale" — its newest point being years
        # old is the correct state, not a degraded one.
        freshness = "not_applicable"
    elif age_hours is None:
        freshness = "unknown"
    else:
        freshness = "fresh" if age_hours <= limit else "stale"
    provisional_count = sum(bool(row.get("provisional")) for row in rows)
    datum_values = sorted({str(row.get("datum")) for row in rows if row.get("datum")})
    datum_status = "declared" if datum_values else ("missing" if policy["datum_required"] else "not_required")
    certified_count = sum(not bool(row.get("provisional")) for row in rows)
    healthy = freshness in ("fresh", "not_applicable")
    return {
        "latest_observed_at": latest.isoformat() if latest else None,
        "age_hours": age_hours,
        "freshness": freshness,
        "freshness_limit_hours": limit,
        "provisional_count": provisional_count,
        "certified_count": certified_count,
        "datum_status": datum_status,
        "datums": datum_values,
        "ingest_health": "healthy" if rows and healthy else ("stale" if rows else "empty"),
    }


def native_alerts(kind: str, metric: str, rows: list[dict[str, Any]], parse_dt) -> list[dict[str, Any]]:
    policy = series_policy(kind, metric)
    threshold = policy["threshold"]
    if threshold is None:
        return []      # reference series — deliberately not an alerting surface
    if not threshold.get("provenance"):
        raise ValueError(f"threshold_without_provenance:{kind}:{metric}")
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
