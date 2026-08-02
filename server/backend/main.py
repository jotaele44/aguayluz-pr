"""
AguaYLuz-PR dashboard API
=========================
Thin FastAPI read layer over the module's canonical JSONL corpus + GeoJSON +
pre-baked outputs. Stdlib only (json) — no DB. This module carries REAL data
(federation status: ready_for_live), so nothing here is synthetic.

Start (from repo root):
    uvicorn server.backend.main:app --reload --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
GEO = DATA / "geo"
OUTPUTS = ROOT / "outputs"

app = FastAPI(title="AguaYLuz-PR API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _json(path: Path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text())


# Eager-load the canonical corpus once at import (fail-fast on missing files).
ASSETS = _jsonl(DATA / "utility_assets.jsonl")
EVENTS = _jsonl(DATA / "service_events.jsonl") + _jsonl(DATA / "aee_incidents.jsonl")
READINGS = {
    "reservoir": _jsonl(DATA / "reservoir_levels.jsonl"),
    "generation": _jsonl(DATA / "generation_readings.jsonl"),
    "reliability": _jsonl(DATA / "reliability_readings.jsonl"),
}
SUMMARY = _json(OUTPUTS / "base44_export.json", {})
REVIEW = _json(OUTPUTS / "review_queue.json", {})


@app.get("/health")
def health():
    return {
        "status": "ok",
        "counts": {
            "assets": len(ASSETS),
            "events": len(EVENTS),
            "readings": {k: len(v) for k, v in READINGS.items()},
        },
        "readiness": {
            "module_status": SUMMARY.get("status"),
            "coverage_pct": SUMMARY.get("coverage_pct"),
            "confidence_avg": SUMMARY.get("confidence_avg"),
            "records_total": SUMMARY.get("records_total"),
            "records_review": SUMMARY.get("records_review"),
            "records_blocked": SUMMARY.get("records_blocked"),
        },
    }


@app.get("/assets")
def assets(asset_type: str | None = None, municipality: str | None = None, status: str | None = None):
    rows = ASSETS
    if asset_type:
        rows = [a for a in rows if a.get("asset_type") == asset_type]
    if municipality:
        rows = [a for a in rows if (a.get("municipality") or "").lower() == municipality.lower()]
    if status:
        rows = [a for a in rows if a.get("status") == status]
    return rows


@app.get("/assets.geojson")
def assets_geojson():
    feats = []
    for a in ASSETS:
        if a.get("lat") is None or a.get("lon") is None:
            continue
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [a["lon"], a["lat"]]},
            "properties": {
                "asset_id": a.get("asset_id"),
                "name": a.get("asset_name"),
                "asset_type": a.get("asset_type"),
                "subtype": a.get("asset_subtype"),
                "municipality": a.get("municipality"),
                "operator": a.get("operator"),
                "status": a.get("status"),
                "evidence_tier": a.get("evidence_tier"),
            },
        })
    return {"type": "FeatureCollection", "features": feats}


@app.get("/events")
def events(event_type: str | None = None, municipality: str | None = None):
    rows = EVENTS
    if event_type:
        rows = [e for e in rows if e.get("event_type") == event_type]
    if municipality:
        rows = [e for e in rows if (e.get("municipality") or "").lower() == municipality.lower()]
    return rows


@app.get("/readings")
def readings(kind: str = "reservoir", asset_id: str | None = None):
    if kind not in READINGS:
        raise HTTPException(400, f"unknown kind '{kind}' (use {list(READINGS)})")
    rows = READINGS[kind]
    if asset_id:
        rows = [r for r in rows if r.get("asset_id") == asset_id]
    return rows


@app.get("/municipios.geojson")
def municipios_geojson():
    path = GEO / "pr_municipios.geojson"
    if not path.exists():
        return JSONResponse({"type": "FeatureCollection", "features": []})
    return JSONResponse(json.loads(path.read_text()))


@app.get("/review-queue")
def review_queue():
    if isinstance(REVIEW, list):
        return REVIEW
    return REVIEW.get("records") or REVIEW.get("items") or REVIEW


@app.get("/summary")
def summary():
    return SUMMARY
