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
# In-memory patches for event/asset acknowledgements & flags (volatile).
_event_patches: dict[str, dict[str, Any]] = {}
_asset_patches: dict[str, dict[str, Any]] = {}


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


@app.patch("/assets/{asset_id}")
async def patch_asset(asset_id: str, request: Request) -> JSONResponse:
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


@app.get("/events/{event_id}")
def event_detail(event_id: str) -> JSONResponse:
    for e in _events:
        if str(e.get("event_id", "")) == event_id:
            merged = {**e, **_event_patches.get(event_id, {})}
            return JSONResponse(merged)
    raise HTTPException(status_code=404, detail="Event not found")


@app.patch("/events/{event_id}")
async def patch_event(event_id: str, request: Request) -> JSONResponse:
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
            if (a.get("asset_type") or "").lower() in types
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


@app.get("/export/report.html")
def export_report_html() -> "HTMLResponse":
    """Generate a printable HTML status report for the dashboard."""
    from fastapi.responses import HTMLResponse
    from datetime import datetime, timezone

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
    from collections import Counter
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
