# AguaYLuz-PR Dashboard

> **Diagnostic-only surface (ADR 0001, Phase 2).** This repo's dashboard is a
> development and diagnostic tool for this producer only. The supported product
> surface for the PRII federation is the hub app
> (`thehub-pr/server/frontend`), which renders this producer's data alongside
> the other engines. See `thehub-pr/docs/adr/0001-federated-engines-single-hub.md`.

Local-only React dashboard for the AguaYLuz water & power continuity module.
Same federation process — Vite + React (JSX) + Tailwind + shadcn/ui + react-query,
Auth stripped, **MapLibre GL** map. This module carries **real** data
(`federation.json` gate `federation_readiness_gate.ready_for_hub_live_execution`
is `true`), so nothing here is synthetic.
Base44 auth stripped, **MapLibre GL** map, shared design system via
`@pr-federation/react`. This module carries **real** data (`federation.json` gate
`federation_readiness_gate.ready_for_hub_live_execution` is `true`), so nothing
here is synthetic.

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

Counts below are the current corpus; every figure the UI displays is read from
the backend, so they track the data rather than this file.

- **Overview** — corpus coverage (mapped vs geometry-less assets, municipio join
  rate, active alerts), sector cards, reservoir trend, recent events.
- **Map** — geolocated assets colored by type over the 78 municipio boundaries,
  plus an opt-in **alert layer** colored by severity (life-safety criticals can be
  isolated). The footer states mapped **of total**: a large share of the corpus
  (canal segments, historic aqueduct alignments) has no geometry and is reachable
  only from the assets table.
- **Assets** — the full corpus with type, **subtype**, status, needs-review and
  **unmapped-only** filters; all filters are URL-synced, so a filtered view is
  shareable. Rows flag assets that never appear on the map.
- **Alerts** — the operational alert layer (`docs/ALERT_SYSTEM.md`): the
  data-driven `AlertEvent`s promoted from ingested signals, faceted by module,
  status, review state, evidence tier, and life-safety criticality. Detail view
  carries validation notes (VAL-001..010), structural flags, gap status, linked
  assets, and dependency edges.
- **Outages** — service events (outages, interruptions) with affected area,
  municipio/zone, and customer counts.
- **Monitoring** — recharts time-series: reservoir levels (USGS), generation
  MWh (EIA, summed by month), and grid reliability (SAIDI/SAIFI/CAIDI).
- **Review** — the 303 records pending human adjudication, with severity/tier.
- Header KPIs from `outputs/hub_export.json` (coverage %, readiness).

## Backend (`server/backend/main.py`)
Reads `data/*.jsonl` (utility_assets 408, service_events+aee_incidents 8,
reservoir/generation/reliability readings), `data/geo/pr_municipios.geojson`,
and `outputs/{hub_export,review_queue}.json` — stdlib only, no DB. CORS
allows `:5173`.
- **Monitoring** — recharts time series over the three ingested reading kinds:
  reservoir levels and groundwater levels (USGS NWIS) and coastal water levels
  (NOAA CO-OPS). Collection gaps are shaded rather than interpolated, and >2σ
  readings are flagged.
- **Review** — records pending human adjudication, with severity/tier.
- **System & Tools** — which backend channels are configured (auth, Slack, ntfy,
  email, AI, Sentry), the freshness of every canonical output and corpus, and the
  operator actions (run federation export, send status alert, open status report).
  Each tool states its precondition instead of failing at click time.
- Header KPIs from `/health` + `outputs/base44_export.json` (coverage %, readiness).

## Backend (`server/backend/main.py`)

Reads `data/*.jsonl` (`utility_assets`, `service_events` + `aee_incidents`,
`alert_events` + its dependency/gap sidecars, and the reservoir / groundwater /
coastal reading series), `data/geo/pr_municipios.geojson`, and
`outputs/{base44_export,review_queue}.json` — stdlib only, no DB. CORS allows
`:5173`.

Endpoints the dashboard consumes: `/health`, `/assets*`, `/events*`, `/alerts*`
(list, detail, facets, `.geojson`, dependencies, gaps), `/readings`,
`/review-queue*`, `/summary`, `/summary/sectors`, `/summary/coverage`,
`/system/status`, `/export/report.html`.

## Offline export

`npm run build:export` (`VITE_OFFLINE=1`) writes a single self-contained
`export-standalone/index.html` that opens over `file://`. It resolves data from
the baked `src/lib/snapshot.json` instead of fetching; keys are API paths
(`/health`, `/assets`, `/alerts`, …), and any path absent from the snapshot falls
back to an empty result. The committed snapshot is `{}`, so a standalone export is
only as populated as the snapshot you bake before building.
