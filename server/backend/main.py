"""AguaYLuz-PR FastAPI backend.

Serves data/*.jsonl + data/geo/*.geojson + outputs/*.json over HTTP for the
React dashboard (dashboard/src/lib/api.js). Stdlib only for data I/O.

Run from repo root:
    uvicorn server.backend.main:app --reload --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA = REPO_ROOT / "data"
OUTPUTS = REPO_ROOT / "outputs"

READINGS_FILES: dict[str, Path] = {
    "reservoir": DATA / "reservoir_levels.jsonl",
    "generation": DATA / "generation.jsonl",
    "reliability": DATA / "reliability.jsonl",
}

app = FastAPI(title="AguaYLuz-PR")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
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


# Load at startup; restart server to pick up data changes.
_assets: list[dict[str, Any]] = _load_jsonl(DATA / "utility_assets.jsonl")
_events: list[dict[str, Any]] = (
    _load_jsonl(DATA / "service_events.jsonl") + _load_jsonl(DATA / "aee_incidents.jsonl")
)
_municipios_geojson: dict[str, Any] = _load_json(
    DATA / "geo" / "pr_municipios.geojson",
    {"type": "FeatureCollection", "features": []},
)


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


@app.get("/events")
def events(
    type: str | None = Query(default=None),
    municipio: str | None = Query(default=None),
) -> JSONResponse:
    result = _events
    if type:
        result = [e for e in result if e.get("event_type") == type]
    if municipio:
        result = [e for e in result if e.get("municipality") == municipio]
    return JSONResponse(result)


@app.get("/readings")
def readings(kind: str = Query(default="reservoir")) -> JSONResponse:
    path = READINGS_FILES.get(kind)
    if path is None:
        return JSONResponse([])
    return JSONResponse(_load_jsonl(path))


@app.get("/review-queue")
def review_queue() -> JSONResponse:
    data = _load_json(OUTPUTS / "review_queue.json")
    if not data:
        return JSONResponse([])
    return JSONResponse(data.get("items", []))


@app.get("/summary")
def summary() -> JSONResponse:
    return JSONResponse(_load_json(OUTPUTS / "base44_export.json", {}))
