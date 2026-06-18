# AguaYLuz-PR Dashboard

Local-only React dashboard for the AguaYLuz water & power continuity module.
Same federation process — Vite + React (JSX) + Tailwind + shadcn/ui + react-query,
Base44 auth stripped, **MapLibre GL** map. This module carries **real** data
(`federation.json` status `ready_for_live`), so nothing here is synthetic.

## Run

```bash
# 1. Backend (from repo root) — thin FastAPI over the canonical JSONL + GeoJSON, on :8000
pip install -r server/backend/requirements.txt   # fastapi, uvicorn (stdlib otherwise)
uvicorn server.backend.main:app --reload --port 8000

# 2. Frontend (this dir) on :5173
npm install
npm run dev
```

Open http://localhost:5173. (`VITE_API_BASE` overrides the API base; default
`http://localhost:8000`.)

## What it shows
- **Map** — 351 geolocated utility assets colored by type (power / water /
  wastewater) over the 78 PR municipio boundaries; click an asset for detail.
- **Assets** — all 408 assets, filter by type, search; tier/status badges.
- **Outages** — service events (outages, interruptions) with affected area,
  municipio/zone, and customer counts.
- **Monitoring** — recharts time-series: reservoir levels (USGS), generation
  MWh (EIA, summed by month), and grid reliability (SAIDI/SAIFI/CAIDI).
- **Review** — the 303 records pending human adjudication, with severity/tier.
- Header KPIs from `outputs/base44_export.json` (coverage %, readiness).

## Backend (`server/backend/main.py`)
Reads `data/*.jsonl` (utility_assets 408, service_events+aee_incidents 8,
reservoir/generation/reliability readings), `data/geo/pr_municipios.geojson`,
and `outputs/{base44_export,review_queue}.json` — stdlib only, no DB. CORS
allows `:5173`.
