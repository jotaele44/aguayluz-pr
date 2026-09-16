# Backend Assessment & Development Plan — aguayluz-pr

## Scope & method

Read-only assessment of the backend at `main` (`64deea0`, "Declare cave karst conformance
scope"). `aguayluz-pr` is the water/power/utility-infrastructure producer node in the PRII
(Puerto Rico Integrated Intelligence) federation: it ingests public water-disruption, power,
tide/storm, drought, and regulatory data for Puerto Rico, plus a cave/karst registry and an
environmental source→pathway→receptor exposure graph, and exports a normalized federation
package that `thehub-pr` (the federation hub) aggregates. Per this repo's own ADR-0001, the
FastAPI service documented below is an explicitly labeled diagnostic-only surface for this
producer — the supported product surface for the federation is the hub app. This document
does not duplicate that framing; it assesses backend completion underneath it.

## Tech stack & backend inventory

- **Framework**: FastAPI. Two app entry points: `server/backend/main.py` (44 KB, the fuller
  API) and `server/backend/app.py` (18 KB, the "canonical" app actually served by the
  desktop build — re-mounts most of `main.py`'s routes, overrides two, adds a monitoring
  incident ledger).
- **Storage**: flat-file JSONL/GeoJSON under `data/`; no SQL database backs the main API.
  `migrations/federation_mvt_v1.sql` and `federation_spatial_v1.sql` exist for a separate
  PostGIS/MVT tile-export path only.
- **Auth**: single shared-secret bearer token (`API_SECRET_KEY`) via a `_require_key`
  dependency, gating mutating routes only. No per-user accounts/RBAC.
- **Endpoints** (by router):
  - `main.py`: `/health`, `/assets` (+`/assets/{id}/events`, `PATCH /assets/{id}`,
    `/assets.geojson`), `/municipios.geojson` + `/municipios/{name}/summary`, `/events`
    (list/filter/SSE stream/`{id}`+PATCH), `/readings`, `/review-queue` +
    `POST /review-queue/{ref}/decision`, `/summary` (+`/sectors`,`/coverage`),
    `/system/status`, `/auth/status`, `/alerts/*` (list/facets/geojson/dependencies/gaps/
    detail), `POST /admin/run-export`, `POST /ai/query` (Anthropic API proxy),
    `/export/report.html`, `POST /notify`.
  - `app.py`: re-mounts the above minus two overrides, adds `/monitoring/*` (append-only,
    hash-chain-verified incident ledger — `monitoring_incident_ledger.py`),
    `/export/monitoring.json`, `/export/federation/monitoring-alerts.json`.
  - `water_disruption_api.py`: `/water-disruption/*` — idempotent intake
    (`Idempotency-Key`/`X-Shadow-Mode` headers), validation queue, incident lifecycle
    (transition/merge/split/retract), HTML console.
  - `cave_karst_api.py`, `environmental_exposure_api.py`, `regulatory_api.py`: read-mostly
    domain routers for the cave/karst registry, the environmental exposure graph, and
    regulatory observations + human-adjudicated entity links.
- **Business logic**: `src/aguayluz/` (~20 modules) — `alerts.py`, `alert_promotion/`,
  `alert_validation.py`, `water_alerts.py`, `water_balance.py`, `cave_karst.py`,
  `environmental_exposure.py`, `regulatory_db.py`, `regulatory_links.py`,
  `spatial_analysis.py`, `validation.py`, `models.py`.
- **Ingestion pipeline**: 50+ `scripts/ingest_*.py` scripts against USGS (7 APIs), EIA,
  NOAA (tides + NHC storms), FEMA, OSHA, SDWIS, HIFLD, OSM, NEON, EPA ECHO, USDM — this is
  the actual bulk of the backend, each source with a matching test.
- **Background jobs**: none in-process; refresh is GitHub Actions cron-driven
  (`refresh.yml`); `POST /admin/run-export` runs the exporter synchronously in-request.
- **Tests/CI**: 120 test files, `pytest-cov` gate `fail_under = 80` (measured 84%); 22
  workflows (`validate.yml`, `codeql.yml`, `pip-audit.yml`, `secret-scan.yml`,
  `gui-capability-parity.yml`, `federation-compatibility.yml`, plus per-domain live-probe/
  freeze gates).

## Completion assessment

- **Fully implemented**: the FastAPI read API; alert/incident lifecycle with hash-chain
  audit log; water-disruption shadow-mode validation workflow; cave/karst and
  environmental-exposure read APIs; ingestion for ~12 primary sources; CI/coverage gating.
- **Partially implemented (self-declared)**: `federation.json` reports
  `PRODUCTION_REAL_DATA_PARTIAL`. NEON stream-chemistry ingestion silently no-ops without an
  API token. Laguna Cartagena basin has a documented data gap (`docs/LAGUNA_CARTAGENA_GAP.md`).
  Water-disruption incident service is deliberately in shadow mode
  (`notifications_enabled: false`, `production_promotion_enabled: false`).
- **No TODO/FIXME/NotImplementedError/stub markers found** in code search — incompleteness
  here is tracked deliberately via `federation.json`, not left as dead code.
- **Missing entirely**: persistent database for mutable API state (`_decisions`,
  `_event_patches`, `_asset_patches` are in-memory dicts in `main.py`, lost on restart);
  multi-user auth/RBAC; a job queue (exports run synchronously in-request).

## Development plan — hardest tasks first

Ordering rationale: the two structural items (persistence, shadow-mode promotion) reshape
how every mutating endpoint behaves, so they're sequenced before narrower fixes — solving
them first avoids redoing endpoint-level work twice. Federation-wide auth is listed but
tracked as blocked on `thehub-pr`'s cross-repo design (see that repo's plan doc) rather than
owned here.

1. **Replace in-memory mutable state with real persistence** (`_decisions`,
   `_event_patches`, `_asset_patches` in `server/backend/main.py`) — Effort: **L**.
   Touches every mutating endpoint's semantics (review decisions, patches currently vanish
   on restart); needs a SQLite/Postgres-backed store and a migration for the JSON-in-TEXT
   patterns already used elsewhere in this repo (`schema_sqlite.sql`-style). No external
   blockers — hardest because of surface area, not unknowns.
2. **Promote water-disruption shadow mode toward production** — Effort: **L**. Requires
   wiring real notification dispatch and production-promotion gates without breaking the
   fail-closed validation state machine already built in `water_disruption.py` (31 KB).
   Hard because the design intentionally resists automatic promotion; this is a policy
   decision as much as an engineering one — needs an explicit go/no-go per alert class.
3. **NEON water-quality metric disaggregation** — Effort: **M**. NEON's `water_quality`
   metric bundles 4 distinct products under one metric name that the current
   `SERIES_METADATA_REGISTRY` schema can't describe without mislabeling. Needs a schema
   change plus a migration of existing readings — a data-model correctness fix, not just a
   config tweak.
4. **Adopt the federation-wide auth contract once `thehub-pr` ships it** — Effort: **M**
   (once the contract exists). Blocked externally on `thehub-pr`'s cross-repo auth design
   (see that repo's plan doc, federation-wide section); until then the single shared-secret
   `API_SECRET_KEY` remains a known, accepted gap for a single-operator diagnostic tool.
5. **Laguna Cartagena / regulatory entity-linkage review-queue backlog** — Effort: **M**,
   open-ended. `regulatory_api.py`'s entity-link decision endpoint is fail-closed by design
   (can't approve with open contradictions), but there's no automated contradiction
   resolution path, so queue growth is unbounded without more reviewer tooling.

## Quick wins (sequenced after/alongside the above, not skipped)

- Make `POST /admin/run-export` async/backgrounded instead of blocking the request thread.
- De-duplicate the reading-vector/asset-status helper logic that has drifted slightly
  between `main.py` and `app.py` (already flagged as a past drift source in code comments).
