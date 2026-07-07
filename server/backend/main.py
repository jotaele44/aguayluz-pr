"""AguaYLuz-PR FastAPI backend.

Serves data/*.jsonl + data/geo/*.geojson + outputs/*.json over HTTP for the
React dashboard (dashboard/src/lib/api.js). Stdlib only for data I/O.

Run from repo root:
    uvicorn server.backend.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA = REPO_ROOT / "data"
OUTPUTS = REPO_ROOT / "outputs"
SCRIPTS = REPO_ROOT / "scripts"

READINGS_FILES: dict[str, Path] = {
    "reservoir": DATA / "reservoir_levels.jsonl",
    "generation": DATA / "generation_readings.jsonl",
    "reliability": DATA / "reliability_readings.jsonl",
}

SECTOR_TYPE_MAP: dict[str, list[str]] = {
    "power": ["power_plant", "substation", "transmission_line", "generation"],
    "water": ["water_treatment", "water_distribution", "reservoir", "pump_station", "water"],
    "wastewater": ["wastewater_treatment", "sewage", "wastewater"],
    "telecom": ["cell_tower", "fiber", "telecom", "communications"],
}

app = FastAPI(title="AguaYLuz-PR")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


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
    try:
        dt = datetime.fromisoformat(s)
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

# In-memory store for review decisions (survives only until server restart).
_decisions: dict[str, str] = {}


@app.get("/health")
def health() -> JSONResponse:
    readings_counts = {k: len(_load_jsonl(p)) for k, p in READINGS_FILES.items()}
    base44 = _load_json(OUTPUTS / "base44_export.json")
    readiness: dict[str, Any] = {}
    if base44:
        readiness = {
            "coverage_pct": base44.get("coverage_pct"),
            "module_status": base44.get("status"),
            "records_review": base44.get("records_review"),
        }
    return JSONResponse({
        "status": "ok",
        "counts": {
            "assets": len(_assets),
            "events": len(_events),
            "readings": readings_counts,
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
    total = len(result)
    result = result[offset:]
    if limit is not None:
        result = result[:limit]
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
                dt = _parse_dt(r.get("timestamp") or r.get("date") or r.get("time"))
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
async def review_decision(ref: str, request: Request) -> JSONResponse:
    body = await request.json()
    decision = body.get("decision")
    if decision not in ("accept", "reject", "skip"):
        raise HTTPException(status_code=400, detail="decision must be accept, reject, or skip")
    _decisions[ref] = decision
    return JSONResponse({"ref": ref, "decision": decision, "ok": True})


@app.get("/summary")
def summary() -> JSONResponse:
    return JSONResponse(_load_json(OUTPUTS / "base44_export.json", {}))


@app.get("/summary/sectors")
def summary_sectors() -> JSONResponse:
    sectors: dict[str, dict[str, Any]] = {}
    for sector, types in SECTOR_TYPE_MAP.items():
        sector_assets = [
            a for a in _assets
            if any(t in (a.get("asset_type") or "").lower() for t in types)
        ]
        active = sum(1 for a in sector_assets if a.get("status") == "active")
        sectors[sector] = {
            "total": len(sector_assets),
            "active": active,
            "pct_active": round(active / len(sector_assets) * 100, 1) if sector_assets else 0,
        }
    return JSONResponse(sectors)


@app.post("/admin/run-export")
def run_export() -> JSONResponse:
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


@app.get("/events/stream")
async def events_stream() -> StreamingResponse:
    """SSE endpoint: pushes latest 20 events every 5 s."""
    async def generator():
        while True:
            payload = _events[-20:]
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.post("/ai/query")
async def ai_query(request: Request) -> JSONResponse:
    """Send a plain-language question about the data to Claude.

    Requires ANTHROPIC_API_KEY env var. Gracefully returns 503 if not set.
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
