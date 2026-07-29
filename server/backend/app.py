"""Canonical AguaYLuz ASGI application.

Imports the legacy backend intact, then replaces only ``GET /readings`` with a
metric-safe contract.  Keeping the override isolated avoids a high-risk rewrite of
unrelated operator, alert, export, and notification routes.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse

from server.backend import main as legacy

app = legacy.app

READING_VECTOR_REGISTRY: dict[str, dict[str, Any]] = {
    "reservoir": {
        "path": legacy.DATA / "reservoir_levels.jsonl",
        "metrics": {
            "reservoir_elevation": {"units": {"ft"}},
            "reservoir_storage_pct": {"units": {"%"}},
            "streamflow": {"units": {"ft3/s", "ft³/s"}},
            "gage_height": {"units": {"ft"}},
        },
        "metric_required": True,
    },
    "groundwater": {
        "path": legacy.DATA / "groundwater_levels.jsonl",
        "metrics": {"groundwater_level": {"units": {"ft"}}},
        "metric_required": False,
    },
    "coastal": {
        "path": legacy.DATA / "coastal_levels.jsonl",
        "metrics": {"coastal_water_level": {"units": {"ft"}}},
        "metric_required": False,
    },
}


def _reading_dt(row: dict[str, Any]) -> datetime | None:
    return legacy._parse_dt(
        row.get("observed_date") or row.get("timestamp") or row.get("date") or row.get("time")
    )


def _remove_legacy_readings_route() -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", None) == "/readings" and "GET" in getattr(route, "methods", set()))
    ]


_remove_legacy_readings_route()


@app.get("/readings")
def readings(
    kind: str = Query(default="reservoir"),
    metric: str | None = Query(default=None),
    parameter_code: str | None = Query(default=None),
    site_no: str | None = Query(default=None),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
) -> JSONResponse:
    """Return one analytically coherent monitoring series plus response metadata.

    Unknown kinds/metrics fail with HTTP 400.  The multi-metric reservoir corpus
    requires an explicit metric so feet, percent, and discharge can never be
    returned as one implicit series.
    """
    vector = READING_VECTOR_REGISTRY.get(kind)
    if vector is None:
        raise HTTPException(
            status_code=400,
            detail={"error": "unknown_reading_kind", "kind": kind, "allowed": sorted(READING_VECTOR_REGISTRY)},
        )

    metrics: dict[str, dict[str, Any]] = vector["metrics"]
    if metric is None:
        if vector["metric_required"]:
            raise HTTPException(
                status_code=400,
                detail={"error": "metric_required", "kind": kind, "allowed": sorted(metrics)},
            )
        metric = next(iter(metrics))
    if metric not in metrics:
        raise HTTPException(
            status_code=400,
            detail={"error": "unknown_reading_metric", "kind": kind, "metric": metric, "allowed": sorted(metrics)},
        )

    since_dt = legacy._parse_dt(since)
    until_dt = legacy._parse_dt(until)
    if since and since_dt is None:
        raise HTTPException(status_code=400, detail={"error": "invalid_since", "value": since})
    if until and until_dt is None:
        raise HTTPException(status_code=400, detail={"error": "invalid_until", "value": until})
    if since_dt and until_dt and since_dt > until_dt:
        raise HTTPException(status_code=400, detail={"error": "invalid_time_range"})

    rows = legacy._load_jsonl(Path(vector["path"]))
    rows = [row for row in rows if row.get("metric") == metric]
    if parameter_code:
        rows = [row for row in rows if str(row.get("parameter_code") or "") == parameter_code]
    if site_no:
        rows = [row for row in rows if str(row.get("site_no") or "") == site_no]
    if since_dt or until_dt:
        bounded: list[dict[str, Any]] = []
        for row in rows:
            observed = _reading_dt(row)
            if observed is None:
                continue
            if since_dt and observed < since_dt:
                continue
            if until_dt and observed > until_dt:
                continue
            bounded.append(row)
        rows = bounded

    rows = sorted(rows, key=lambda row: (str(row.get("site_no") or ""), str(row.get("observed_date") or ""), str(row.get("parameter_code") or "")))
    units = sorted({str(row.get("unit")) for row in rows if row.get("unit") not in (None, "")})
    parameter_codes = sorted({str(row.get("parameter_code")) for row in rows if row.get("parameter_code") not in (None, "")})
    sites = Counter(str(row.get("site_no") or "unknown") for row in rows)

    return JSONResponse({
        "kind": kind,
        "metric": metric,
        "parameter_code": parameter_code,
        "site_no": site_no,
        "since": since,
        "until": until,
        "record_count": len(rows),
        "site_count": len(sites),
        "units": units,
        "parameter_codes": parameter_codes,
        "mixed_units": len(units) > 1,
        "items": rows,
    })
