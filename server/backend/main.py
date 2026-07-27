"""AguaYLuz-PR FastAPI backend.

Serves data/*.jsonl + data/geo/*.geojson + outputs/*.json over HTTP for the
React dashboard (dashboard/src/lib/api.js). Stdlib only for data I/O.

Run from repo root:
    uvicorn server.backend.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import os as _os
import smtplib as _smtplib
import subprocess
import sys
import urllib.request as _notify_urllib
from collections import Counter
from datetime import datetime, timezone
from email.message import EmailMessage as _EmailMessage
from pathlib import Path
from typing import Any

from fastapi import Depends as _Depends
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA = REPO_ROOT / "data"
OUTPUTS = REPO_ROOT / "outputs"
SCRIPTS = REPO_ROOT / "scripts"

# Monitoring reading kinds -> their canonical JSONL. Every kind here has a producer
# in scripts/ that scripts/refresh.py runs, so an empty series means "no data yet",
# never "no such feed". All three share one record shape (site_no / metric / value /
# observed_date), so the dashboard renders them with a single time-series path.
READINGS_FILES: dict[str, Path] = {
    "reservoir": DATA / "reservoir_levels.jsonl",       # scripts/ingest_usgs_levels.py
    "groundwater": DATA / "groundwater_levels.jsonl",   # scripts/ingest_usgs_groundwater.py
    "coastal": DATA / "coastal_levels.jsonl",           # scripts/ingest_noaa_tides.py
}

# Default page size for GET /events. The service_events corpus includes the full
# EPA SDWIS violation history (tens of thousands of rows, ~13 MB), so an unbounded
# response would make a normal dashboard load download the entire corpus. Callers
# still get the true `total`; pass an explicit `limit` (or a negative value for
# "all") to fetch more. The dashboard's default views only need the most recent slice.
DEFAULT_EVENTS_LIMIT = 500

# Canonical asset_type values for each sector.  Exact-match is used (not substring)
# to prevent "water" matching "wastewater" assets, etc.
SECTOR_TYPE_MAP: dict[str, set[str]] = {
    "power": {"power", "power_plant", "substation", "transmission_line", "generation"},
    "water": {"water", "water_treatment", "water_distribution", "reservoir", "pump_station"},
    "wastewater": {"wastewater", "wastewater_treatment", "sewage"},
    "telecom": {"telecom", "cell_tower", "fiber", "communications"},
}

app = FastAPI(title="AguaYLuz-PR")

# CORS: allow the Vite dev server and any configured ALLOWED_ORIGINS
_cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
_extra = _os.getenv("ALLOWED_ORIGINS", "")
if _extra:
    _cors_origins.extend(o.strip() for o in _extra.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


# Optional API key auth — set API_SECRET_KEY env var to enable.
# Public endpoints (GET /health, GET /assets*, GET /events*, GET /readings*,
# GET /municipios*, GET /export/*) remain open for read-only dashboard access.
# Write / admin endpoints require the key in the Authorization header:
#   Authorization: Bearer <API_SECRET_KEY>
_API_KEY = _os.getenv("API_SECRET_KEY", "")
async def _require_key(request: Request):
    if not _API_KEY:
        return  # auth disabled globally
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    # datetime.fromisoformat only accepts a trailing "Z" from Python 3.11 on. The repo
    # still supports 3.10, where a Z-suffixed value raised ValueError and this returned
    # None — which callers read as "no bound", so `?since=` was silently ignored and the
    # dashboard's 7d/30d/90d ranges returned the entire series. The dashboard sends
    # exactly this shape (`new Date().toISOString()`), as do the canonical corpora.
    text = s.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# Load at startup; restart server to pick up data changes.
_assets: list[dict[str, Any]] = _load_jsonl(DATA / "utility_assets.jsonl")
_events: list[dict[str, Any]] = (
    _load_jsonl(DATA / "service_events.jsonl") + _load_jsonl(DATA / "aee_incidents.jsonl")
)
_municipios_geojson: dict[str, Any] = _load_json(
    DATA / "geo" / "pr_municipios.geojson",
    {"type": "FeatureCollection", "features": []},
)
# The operational alert layer (docs/ALERT_SYSTEM.md) — built by scripts/build_alerts.py
# and validated by scripts/build_alert_system.py. Loaded once at startup like the other
# corpora: it is several MB, so re-parsing per request would dominate every alert call.
_alerts: list[dict[str, Any]] = _load_jsonl(DATA / "alert_events.jsonl")
_alert_edges: list[dict[str, Any]] = _load_jsonl(DATA / "alert_dependency_edges.jsonl")
_alert_gaps: list[dict[str, Any]] = _load_jsonl(DATA / "alert_gaps.jsonl")

# Operational severity at or above which an alert is life-safety critical while still
# actionable. Mirrors aguayluz.alert_promotion.CRITICAL_SEVERITY and, deliberately,
# scripts/federation_export.py `_alert_is_critical` — which defines "actionable" as a
# blocklist (anything not closed/rejected, so a `draft` still counts) rather than an
# allowlist. Matching it exactly is the point: these counts must equal what the Hub
# receives, and an allowlist here silently under-reported drafts by comparison.
CRITICAL_SEVERITY = 4
INACTIVE_ALERT_STATUS = {"closed", "rejected"}

# In-memory store for review decisions (survives only until server restart).
_decisions: dict[str, str] = {}
# In-memory patches for event/asset acknowledgements & flags (volatile).
_event_patches: dict[str, dict[str, Any]] = {}
_asset_patches: dict[str, dict[str, Any]] = {}


@app.get("/health")
def health() -> JSONResponse:
    readings_counts = {k: len(_load_jsonl(p)) for k, p in READINGS_FILES.items()}
    hub_export = _load_json(OUTPUTS / "hub_export.json")
    readiness: dict[str, Any] = {}
    if hub_export:
        readiness = {
            "coverage_pct": hub_export.get("coverage_pct"),
            "module_status": hub_export.get("status"),
            "records_review": hub_export.get("records_review"),
        }
    return JSONResponse({
        "status": "ok",
        "counts": {
            "assets": len(_assets),
            "events": len(_events),
            "readings": readings_counts,
            "alerts": len(_alerts),
            "alerts_active": sum(1 for a in _alerts if _alert_is_actionable(a)),
            "alerts_critical": sum(1 for a in _alerts if _alert_is_critical(a)),
        },
        "readiness": readiness,
    })


@app.get("/assets")
def assets(
    type: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> JSONResponse:
    result = _assets
    if type:
        result = [a for a in result if a.get("asset_type") == type]
    if search:
        needle = search.lower()
        result = [a for a in result if needle in (a.get("asset_name") or "").lower()]
    return JSONResponse(result)


@app.get("/assets/{asset_id}/events")
def asset_events(asset_id: str) -> JSONResponse:
    asset = next((a for a in _assets if a.get("asset_id") == asset_id), None)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    municipio = (asset.get("municipality") or "").lower()
    name = (asset.get("asset_name") or "").lower()
    related = [
        e for e in _events
        if (municipio and municipio in (e.get("municipality") or "").lower())
        or (municipio and municipio in (e.get("affected_area") or "").lower())
        or (name and name in (e.get("affected_area") or "").lower())
    ]
    return JSONResponse(related)


def auth_status_payload() -> dict[str, Any]:
    """Whether API key auth is enabled and which notification channels are configured."""
    return {
        "auth_enabled": bool(_API_KEY),
        "slack_configured": bool(_os.getenv("SLACK_WEBHOOK_URL")),
        "ntfy_configured": bool(_os.getenv("NTFY_TOPIC")),
        "email_configured": bool(_os.getenv("NOTIFY_EMAIL_FROM") and _os.getenv("NOTIFY_EMAIL_TO")),
        "sentry_dsn_set": bool(_os.getenv("SENTRY_DSN")),
        "ai_enabled": bool(_os.getenv("ANTHROPIC_API_KEY")),
    }


@app.get("/auth/status")
def auth_status() -> JSONResponse:
    """Channel configuration only. /system/status is the superset the UI reads."""
    return JSONResponse(auth_status_payload())


@app.patch("/assets/{asset_id}")
async def patch_asset(asset_id: str, request: Request, _=_Depends(_require_key)) -> JSONResponse:  # noqa: B008
    """Update mutable fields (review_status) on an asset."""
    for a in _assets:
        if a.get("asset_id") == asset_id:
            body = await request.json()
            allowed = {"review_status", "status"}
            patch = {k: v for k, v in body.items() if k in allowed}
            _asset_patches.setdefault(asset_id, {}).update(patch)
            return JSONResponse({**a, **_asset_patches[asset_id]})
    raise HTTPException(status_code=404, detail="Asset not found")


@app.get("/assets.geojson")
def assets_geojson() -> JSONResponse:
    features = []
    for a in _assets:
        lat, lon = a.get("lat"), a.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": a,
        })
    return JSONResponse({"type": "FeatureCollection", "features": features})


@app.get("/municipios.geojson")
def municipios_geojson() -> JSONResponse:
    return JSONResponse(_municipios_geojson)


@app.get("/municipios/{name}/summary")
def municipio_summary(name: str) -> JSONResponse:
    name_lower = name.lower()
    mun_assets = [a for a in _assets if (a.get("municipality") or "").lower() == name_lower]
    mun_events = [
        e for e in _events
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
    })


@app.get("/events/stream")
async def events_stream() -> StreamingResponse:
    """SSE endpoint: pushes latest 20 events every 5 s."""
    async def generator():
        while True:
            payload = _events[-20:]
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/events/{event_id}")
def event_detail(event_id: str) -> JSONResponse:
    for e in _events:
        if str(e.get("event_id", "")) == event_id:
            merged = {**e, **_event_patches.get(event_id, {})}
            return JSONResponse(merged)
    raise HTTPException(status_code=404, detail="Event not found")


@app.patch("/events/{event_id}")
async def patch_event(event_id: str, request: Request, _=_Depends(_require_key)) -> JSONResponse:  # noqa: B008
    """Update mutable fields (resolution_status, review_status) on an event."""
    for e in _events:
        if str(e.get("event_id", "")) == event_id:
            body = await request.json()
            allowed = {"resolution_status", "review_status"}
            patch = {k: v for k, v in body.items() if k in allowed}
            _event_patches.setdefault(event_id, {}).update(patch)
            return JSONResponse({**e, **_event_patches[event_id]})
    raise HTTPException(status_code=404, detail="Event not found")


@app.get("/events")
def events(
    type: str | None = Query(default=None),
    municipio: str | None = Query(default=None),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    offset: int = Query(default=0),
) -> JSONResponse:
    result = _events
    since_dt = _parse_dt(since)
    until_dt = _parse_dt(until)
    if type:
        result = [e for e in result if e.get("event_type") == type]
    if municipio:
        mun = municipio.lower()
        result = [
            e for e in result
            if mun in (e.get("municipality") or "").lower()
            or mun in (e.get("affected_area") or "").lower()
        ]
    if since_dt or until_dt:
        filtered = []
        for e in result:
            dt = _parse_dt(e.get("start_time"))
            if dt is None:
                continue
            if since_dt and dt < since_dt:
                continue
            if until_dt and dt > until_dt:
                continue
            filtered.append(e)
        result = filtered
    # Recent-first so a bounded default page returns the newest events (the SDWIS
    # bulk is historical). Stable sort keeps input order among equal timestamps.
    result = sorted(result, key=lambda e: e.get("start_time") or "", reverse=True)
    total = len(result)
    result = result[offset:]
    # Bound the response by default; an explicit non-negative limit overrides it,
    # and an explicit negative limit opts out entirely ("give me everything").
    effective_limit = DEFAULT_EVENTS_LIMIT if limit is None else limit
    if effective_limit is not None and effective_limit >= 0:
        result = result[:effective_limit]
    return JSONResponse({"total": total, "offset": offset, "items": result})


@app.get("/readings")
def readings(
    kind: str = Query(default="reservoir"),
    since: str | None = Query(default=None),
) -> JSONResponse:
    path = READINGS_FILES.get(kind)
    if path is None:
        return JSONResponse([])
    data = _load_jsonl(path)
    if since:
        since_dt = _parse_dt(since)
        if since_dt:
            filtered = []
            for r in data:
                # `observed_date` is what every reading producer actually writes
                # (ingest_usgs_levels / _groundwater / noaa_tides); without it the
                # 7d/30d/90d ranges parsed nothing and returned an empty series.
                dt = _parse_dt(
                    r.get("observed_date") or r.get("timestamp") or r.get("date") or r.get("time")
                )
                if dt and dt >= since_dt:
                    filtered.append(r)
            data = filtered
    return JSONResponse(data)


@app.get("/review-queue")
def review_queue(
    offset: int = Query(default=0),
    limit: int | None = Query(default=None),
    severity: str | None = Query(default=None),
    tier: str | None = Query(default=None),
) -> JSONResponse:
    data = _load_json(OUTPUTS / "review_queue.json")
    items: list[dict[str, Any]] = data.get("items", []) if data else []
    items = [i for i in items if _decisions.get(i.get("record_ref", "")) not in ("accept", "reject")]
    if severity:
        items = [i for i in items if i.get("severity") == severity]
    if tier:
        items = [i for i in items if i.get("evidence_tier") == tier]
    total = len(items)
    items = items[offset:]
    if limit is not None:
        items = items[:limit]
    return JSONResponse({"total": total, "offset": offset, "items": items})


@app.post("/review-queue/{ref}/decision")
async def review_decision(ref: str, request: Request, _=_Depends(_require_key)) -> JSONResponse:  # noqa: B008
    body = await request.json()
    decision = body.get("decision")
    if decision not in ("accept", "reject", "skip"):
        raise HTTPException(status_code=400, detail="decision must be accept, reject, or skip")
    _decisions[ref] = decision
    return JSONResponse({"ref": ref, "decision": decision, "ok": True})


@app.get("/summary")
def summary() -> JSONResponse:
    return JSONResponse(_load_json(OUTPUTS / "hub_export.json", {}))


@app.get("/summary/sectors")
def summary_sectors() -> JSONResponse:
    sectors: dict[str, dict[str, Any]] = {}
    for sector, types in SECTOR_TYPE_MAP.items():
        sector_assets = [
            a for a in _assets
            if (a.get("asset_type") or "").lower() in types
        ]
        active = sum(1 for a in sector_assets if a.get("status") == "active")
        sectors[sector] = {
            "total": len(sector_assets),
            "active": active,
            "pct_active": round(active / len(sector_assets) * 100, 1) if sector_assets else 0,
        }
    return JSONResponse(sectors)


# Municipality placeholders written by ingests that could not resolve a real municipio.
# They are not a municipality — counting them as "joined" would overstate geo coverage.
UNJOINED_MUNICIPALITY = {"puerto rico", "unknown", "", "n/a"}


@app.get("/summary/coverage")
def summary_coverage() -> JSONResponse:
    """Corpus coverage: what the map and the municipio joins actually reach.

    A large share of the asset corpus is geometry-less (canal segments, historic
    aqueduct alignments) or carries an unresolved municipality. Both are invisible in
    a map-first UI, which reads as "this is everything" — so report them as first-class
    numbers, alongside the subtype facet the assets table filters on.
    """
    total = len(_assets)
    mapped = sum(1 for a in _assets
                 if isinstance(a.get("lat"), (int, float))
                 and isinstance(a.get("lon"), (int, float)))
    joined = sum(1 for a in _assets
                 if (a.get("municipality") or "").strip().lower() not in UNJOINED_MUNICIPALITY)
    pct = lambda n: round(n / total * 100, 1) if total else 0.0  # noqa: E731

    return JSONResponse({
        "assets": {
            "total": total,
            "mapped": mapped,
            "unmapped": total - mapped,
            "pct_mapped": pct(mapped),
            "municipio_joined": joined,
            "municipio_unjoined": total - joined,
            "pct_municipio_joined": pct(joined),
        },
        "review_status": dict(Counter(a.get("review_status") or "unknown" for a in _assets)),
        "evidence_tier": dict(Counter(a.get("evidence_tier") or "unknown" for a in _assets)),
        "asset_type": dict(Counter(a.get("asset_type") or "unknown" for a in _assets)),
        # Facet options for the assets table — derived, so a new ingest's subtypes are
        # filterable without a frontend change.
        "asset_subtype": dict(
            Counter(a.get("asset_subtype") for a in _assets if a.get("asset_subtype")).most_common()
        ),
        # Which subtypes are the map-invisible ones, so the UI can explain the gap
        # instead of only reporting its size.
        "unmapped_by_subtype": dict(
            Counter(a.get("asset_subtype") or "unknown" for a in _assets
                    if not isinstance(a.get("lat"), (int, float))).most_common(10)
        ),
    })


def _artifact_status(path: Path) -> dict[str, Any]:
    """Presence + last-write time of a canonical output, for the System page."""
    if not path.exists():
        return {"present": False, "path": str(path.relative_to(REPO_ROOT))}
    stat = path.stat()
    return {
        "present": True,
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


@app.get("/system/status")
def system_status() -> JSONResponse:
    """Which operator tools are wired, and how fresh the canonical outputs are.

    Superset of /auth/status: the dashboard's tools (export, notify, AI recap, report)
    each depend on backend configuration the browser cannot see, so they were failing
    at click time. This lets the UI disable a tool with a reason instead.
    """
    exports = REPO_ROOT / "exports" / "federation"
    return JSONResponse({
        **auth_status_payload(),
        "artifacts": {
            "hub_export": _artifact_status(OUTPUTS / "hub_export.json"),
            "review_queue": _artifact_status(OUTPUTS / "review_queue.json"),
            "integration_report": _artifact_status(OUTPUTS / "integration_report.json"),
            "source_manifest": _artifact_status(OUTPUTS / "source_manifest.json"),
            "alert_events_geojson": _artifact_status(OUTPUTS / "alert_events.geojson"),
            "federation_manifest": _artifact_status(exports / "manifest.json"),
        },
        "corpora": {
            "utility_assets": _artifact_status(DATA / "utility_assets.jsonl"),
            "service_events": _artifact_status(DATA / "service_events.jsonl"),
            "alert_events": _artifact_status(DATA / "alert_events.jsonl"),
            **{f"readings_{k}": _artifact_status(p) for k, p in READINGS_FILES.items()},
        },
    })


# ── Operational alert layer (docs/ALERT_SYSTEM.md) ───────────────────────────
# Read-only projections of data/alert_events.jsonl and its dependency/gap sidecars.
# The exporter already projects these into the canonical `alerts` stream for the Hub;
# these endpoints give this producer's own dashboard the same view.


def _alert_is_actionable(alert: dict[str, Any]) -> bool:
    """Still in a live lifecycle state — anything the exporter has not retired."""
    return str(alert.get("status")) not in INACTIVE_ALERT_STATUS


def _alert_is_critical(alert: dict[str, Any]) -> bool:
    """Life-safety threshold cleared AND the alert is still actionable."""
    severity = alert.get("severity")
    return (
        isinstance(severity, int)
        and severity >= CRITICAL_SEVERITY
        and _alert_is_actionable(alert)
    )


def _alert_municipios(alert: dict[str, Any]) -> list[str]:
    munis = alert.get("municipalities")
    return [str(m) for m in munis] if isinstance(munis, list) else []


@app.get("/alerts")
def alerts(
    module_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    tier: str | None = Query(default=None),
    severity_min: int | None = Query(default=None),
    critical_only: bool = Query(default=False),
    municipio: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    offset: int = Query(default=0),
) -> JSONResponse:
    """Paged alert list, newest first.

    Bounded by DEFAULT_EVENTS_LIMIT for the same reason /events is: the alert corpus
    carries the full SDWIS-derived contamination history. Callers get the true
    `total`; pass an explicit `limit` (negative for "all") to page past the default.
    """
    result = _alerts
    if module_id:
        result = [a for a in result if a.get("module_id") == module_id]
    if status:
        result = [a for a in result if a.get("status") == status]
    if review_status:
        result = [a for a in result if a.get("review_status") == review_status]
    if tier:
        result = [a for a in result if a.get("evidence_tier") == tier]
    if severity_min is not None:
        result = [a for a in result
                  if isinstance(a.get("severity"), int) and a["severity"] >= severity_min]
    if critical_only:
        result = [a for a in result if _alert_is_critical(a)]
    if municipio:
        needle = municipio.lower()
        result = [a for a in result
                  if any(needle in m.lower() for m in _alert_municipios(a))]
    if q:
        needle = q.lower()
        result = [
            a for a in result
            if needle in (a.get("source_title") or "").lower()
            or needle in (a.get("asset_name") or "").lower()
            or needle in (a.get("alert_id") or "").lower()
        ]
    result = sorted(result, key=lambda a: a.get("start_at") or "", reverse=True)
    total = len(result)
    result = result[offset:]
    effective_limit = DEFAULT_EVENTS_LIMIT if limit is None else limit
    if effective_limit is not None and effective_limit >= 0:
        result = result[:effective_limit]
    return JSONResponse({"total": total, "offset": offset, "items": result})


@app.get("/alerts/facets")
def alert_facets() -> JSONResponse:
    """Filter options + counts, derived from the corpus rather than hardcoded in the UI."""
    return JSONResponse({
        "total": len(_alerts),
        "active": sum(1 for a in _alerts if _alert_is_actionable(a)),
        "critical": sum(1 for a in _alerts if _alert_is_critical(a)),
        "mapped": sum(1 for a in _alerts
                      if isinstance(a.get("latitude"), (int, float))
                      and isinstance(a.get("longitude"), (int, float))),
        "module_id": dict(Counter(a.get("module_id") for a in _alerts if a.get("module_id"))),
        "status": dict(Counter(a.get("status") for a in _alerts if a.get("status"))),
        "review_status": dict(Counter(a.get("review_status") for a in _alerts
                                      if a.get("review_status"))),
        "evidence_tier": dict(Counter(a.get("evidence_tier") for a in _alerts
                                      if a.get("evidence_tier"))),
        "severity": dict(Counter(str(a.get("severity")) for a in _alerts
                                 if isinstance(a.get("severity"), int))),
        "gap_status": dict(Counter(a.get("gap_status") for a in _alerts if a.get("gap_status"))),
    })


@app.get("/alerts.geojson")
def alerts_geojson(critical_only: bool = Query(default=False)) -> JSONResponse:
    """Point features for the map layer. Same lat/lon guard as /assets.geojson."""
    features = []
    for a in _alerts:
        if critical_only and not _alert_is_critical(a):
            continue
        lat, lon = a.get("latitude"), a.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {**a, "is_critical": _alert_is_critical(a)},
        })
    return JSONResponse({"type": "FeatureCollection", "features": features})


@app.get("/alerts/dependencies")
def alert_dependencies(
    alert_id: str | None = Query(default=None),
    asset_id: str | None = Query(default=None),
) -> JSONResponse:
    """Dependency edges (data/alert_dependency_edges.jsonl), optionally scoped."""
    rows = _alert_edges
    if alert_id:
        rows = [e for e in rows if alert_id in (e.get("alert_id"), e.get("source_alert_id"))]
    if asset_id:
        rows = [
            e for e in rows
            if asset_id in (e.get("from_asset_id"), e.get("to_asset_id"), e.get("asset_id"))
        ]
    return JSONResponse(rows)


@app.get("/alerts/gaps")
def alert_gaps() -> JSONResponse:
    """The gap log (data/alert_gaps.jsonl) — few rows, returned whole."""
    return JSONResponse(_alert_gaps)


@app.get("/alerts/{alert_id}")
def alert_detail(alert_id: str) -> JSONResponse:
    for a in _alerts:
        if str(a.get("alert_id", "")) == alert_id:
            return JSONResponse({**a, "is_critical": _alert_is_critical(a)})
    raise HTTPException(status_code=404, detail="Alert not found")


@app.post("/admin/run-export")
async def run_export(request: Request, _=_Depends(_require_key)) -> JSONResponse:  # noqa: B008
    script = SCRIPTS / "federation_export.py"
    if not script.exists():
        raise HTTPException(status_code=404, detail="federation_export.py not found")
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr[-2000:] or "Export failed")
    return JSONResponse({"ok": True, "stdout": result.stdout[-2000:]})


@app.post("/ai/query")
async def ai_query(request: Request, _=_Depends(_require_key)) -> JSONResponse:  # noqa: B008
    """Send a plain-language question about the data to Claude.

    Requires ANTHROPIC_API_KEY env var. Gracefully returns 503 if not set.

    Key-guarded like the other mutating routes, and for a sharper reason: this one
    spends money. It forwards the caller's prompt to api.anthropic.com on the
    operator's ANTHROPIC_API_KEY, so an unguarded route on a reachable port is a
    spendable credential rather than just a write surface.
    """
    import os
    import urllib.request as _urllib

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    body = await request.json()
    user_msg = (body.get("query") or "").strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="query field required")

    # Build a compact context snapshot
    c = health()
    counts = json.loads(c.body)["counts"]  # type: ignore[attr-defined]
    system = (
        f"You are an assistant for the AguaYLuz-PR dashboard, tracking Puerto Rico water & power infrastructure. "
        f"Current counts: {counts['assets']} assets, {counts['events']} events. "
        f"Answer concisely in 2-4 sentences. Be factual about what the data shows."
    )

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 512,
        "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }).encode()

    req = _urllib.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with _urllib.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        text = result["content"][0]["text"]
        return JSONResponse({"answer": text})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/export/report.html")
def export_report_html() -> HTMLResponse:
    """Generate a printable HTML status report for the dashboard."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_assets = len(_assets)
    total_events = len(_events)

    # Sector rollup
    sector_rows = ""
    for sector, types in SECTOR_TYPE_MAP.items():
        sa = [a for a in _assets if (a.get("asset_type") or "").lower() in types]
        active = sum(1 for a in sa if a.get("status") == "active")
        pct = round(active / len(sa) * 100, 1) if sa else 0
        sector_rows += f"<tr><td>{sector.title()}</td><td>{len(sa)}</td><td>{active}</td><td>{pct}%</td></tr>\n"

    # Top 10 municipios by event count
    mun_counts = Counter(
        e.get("municipality") or e.get("affected_area") or "Unknown"
        for e in _events
    )
    top10_rows = ""
    for mun, cnt in mun_counts.most_common(10):
        top10_rows += f"<tr><td>{mun}</td><td>{cnt}</td></tr>\n"

    # Recent events
    recent_events = _events[-20:]
    recent_rows = ""
    for e in reversed(recent_events):
        etype = (e.get("event_type") or "event").replace("_", " ").title()
        area = e.get("affected_area") or e.get("municipality") or "—"
        start = (e.get("start_time") or "")[:10]
        recent_rows += f"<tr><td>{etype}</td><td>{area}</td><td>{start}</td></tr>\n"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>AguaYLuz-PR Status Report — {now}</title>
  <style>
    @page {{ margin: 2cm; }}
    body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #1e293b; line-height: 1.6; }}
    h1 {{ font-size: 1.5rem; color: #0c4a6e; border-bottom: 2px solid #0ea5e9; padding-bottom: .5rem; margin-bottom: 1.5rem; }}
    h2 {{ font-size: 1rem; color: #0c4a6e; margin-top: 2rem; margin-bottom: .5rem; }}
    .meta {{ font-size: .8rem; color: #64748b; margin-top: -.75rem; margin-bottom: 1.5rem; }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 2rem; }}
    .kpi {{ border: 1px solid #e2e8f0; border-radius: .5rem; padding: 1rem; text-align: center; }}
    .kpi .val {{ font-size: 2rem; font-weight: 700; color: #0369a1; }}
    .kpi .lbl {{ font-size: .75rem; color: #64748b; text-transform: uppercase; letter-spacing: .05em; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .875rem; }}
    th {{ background: #f1f5f9; text-align: left; padding: .4rem .75rem; border: 1px solid #e2e8f0; font-size: .75rem; text-transform: uppercase; color: #475569; }}
    td {{ padding: .4rem .75rem; border: 1px solid #e2e8f0; }}
    tr:nth-child(even) td {{ background: #f8fafc; }}
    @media print {{ button {{ display: none; }} }}
  </style>
</head>
<body>
  <button onclick="window.print()" style="float:right;padding:.5rem 1rem;background:#0ea5e9;color:#fff;border:none;border-radius:.375rem;cursor:pointer;">Print / Save PDF</button>
  <h1>AguaYLuz-PR Infrastructure Status Report</h1>
  <div class="meta">Generated: {now} &nbsp;|&nbsp; Data: in-memory snapshot</div>

  <div class="kpi-grid">
    <div class="kpi"><div class="val">{total_assets:,}</div><div class="lbl">Total Assets</div></div>
    <div class="kpi"><div class="val">{total_events:,}</div><div class="lbl">Service Events</div></div>
    <div class="kpi"><div class="val">{sum(1 for a in _assets if a.get("status") == "active"):,}</div><div class="lbl">Active Assets</div></div>
  </div>

  <h2>Sector Summary</h2>
  <table>
    <tr><th>Sector</th><th>Total Assets</th><th>Active</th><th>% Active</th></tr>
    {sector_rows}
  </table>

  <h2>Top 10 Affected Municipios (by Event Count)</h2>
  <table>
    <tr><th>Municipio / Area</th><th>Events</th></tr>
    {top10_rows}
  </table>

  <h2>Recent Events (last 20)</h2>
  <table>
    <tr><th>Type</th><th>Area</th><th>Date</th></tr>
    {recent_rows}
  </table>
</body>
</html>"""
    return HTMLResponse(content=html)


# ── Notification dispatch ──────────────────────────────────────────────────────
# Opt-in via env vars:
#   SLACK_WEBHOOK_URL  — Slack incoming webhook (POST JSON)
#   NOTIFY_EMAIL_FROM / NOTIFY_EMAIL_TO / SMTP_HOST — SMTP email alerts
#   NTFY_TOPIC — ntfy.sh push topic (e.g. "aguayluz-pr-alerts")
#
# POST /notify — internal helper called by the dashboard or CI after a critical
# event is detected.  Returns 200 OK regardless; errors are logged but not
# surfaced to the caller so a broken webhook never blocks the dashboard.


def _send_slack(webhook: str, text: str) -> None:
    body = json.dumps({"text": text}).encode()
    req = _notify_urllib.Request(webhook, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with _notify_urllib.urlopen(req, timeout=10):
        pass


def _send_ntfy(topic: str, text: str, title: str = "AguaYLuz-PR Alert") -> None:
    req = _notify_urllib.Request(
        f"https://ntfy.sh/{topic}",
        data=text.encode(),
        headers={"Title": title, "Priority": "high", "Tags": "warning"},
        method="POST",
    )
    with _notify_urllib.urlopen(req, timeout=10):
        pass


def _send_email(from_addr: str, to_addr: str, smtp_host: str, subject: str, body: str) -> None:
    msg = _EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)
    with _smtplib.SMTP(smtp_host, 587, timeout=10) as server:
        server.sendmail(from_addr, [to_addr], msg.as_string())


@app.post("/notify")
async def notify(request: Request, _=_Depends(_require_key)) -> JSONResponse:  # noqa: B008
    """Dispatch a notification to configured channels (Slack, ntfy, email).

    Body: {"message": str, "title": str = "AguaYLuz-PR Alert"}
    """
    body = await request.json()
    message = (body.get("message") or "").strip()
    title = (body.get("title") or "AguaYLuz-PR Alert").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message field required")

    errors: list[str] = []

    slack_url = _os.getenv("SLACK_WEBHOOK_URL")
    if slack_url:
        try:
            _send_slack(slack_url, f"*{title}*\n{message}")
        except Exception as e:
            errors.append(f"slack: {e}")

    ntfy_topic = _os.getenv("NTFY_TOPIC")
    if ntfy_topic:
        try:
            _send_ntfy(ntfy_topic, message, title)
        except Exception as e:
            errors.append(f"ntfy: {e}")

    email_from = _os.getenv("NOTIFY_EMAIL_FROM")
    email_to = _os.getenv("NOTIFY_EMAIL_TO")
    smtp_host = _os.getenv("SMTP_HOST")
    if email_from and email_to and smtp_host:
        try:
            _send_email(email_from, email_to, smtp_host, title, message)
        except Exception as e:
            errors.append(f"email: {e}")

    channels_active = bool(slack_url or ntfy_topic or (email_from and email_to and smtp_host))
    return JSONResponse({"ok": True, "channels_active": channels_active, "errors": errors})
