# aguayluz-pr — Professional Maturity Audit

**Date:** 2026-07-26 · **Method:** static review **plus execution** — every number below came
from running the code in a clean container (Python 3.11.15, Node v22.22.2). Setup followed
this repo's own `hub_callable_commands.setup` (`uv pip install --system -e ".[dev]"`).

Scope: this repository only. Cross-repo comparisons live in
[`thehub-pr/docs/FEDERATION_MATURITY_AUDIT.md`](https://github.com/jotaele44/thehub-pr/blob/main/docs/FEDERATION_MATURITY_AUDIT.md).

---

## Scorecard

| Dim | Area | Score | Evidence |
|---|---|---|---|
| D1 | Functional completeness | **4** | 25 backend routes including GeoJSON and SSE; 11 UI pages over them; the tightest front-to-back fit in the federation |
| D2 | Data reality | **4** | 24 MB of data, **zero synthetic-flagged files** — the best real-data position of any producer |
| D3 | UI craft | **3** | 11 pages, 4.4k LOC, 5 `ErrorBoundary` (most in the federation), 16 loading states — but only 1 empty state and 11 `aria-*` |
| D4 | Test coverage | **4** | `306 passed` (31.5s), 32 test files against 14.0k LOC — a strong ratio |
| D5 | Engineering hygiene | **4** | `ruff check .` clean on the **widest rule set in the federation** (`E,F,I,B,UP,SIM,W`) |
| D6 | Doc accuracy | **4** | `federation.json` accurately caveats outage granularity as snapshot-grade pending MiLUMA data-sharing |

**Overall: the best-balanced node in the federation.** Real data, a proportionate UI, a wide
lint rule set that passes, and honest caveats. Nothing here is fake and nothing is
dramatically out of proportion. The gaps are ordinary polish items, not structural problems.

---

## What is fully developed vs. what is not

**PRODUCTION**

| Module | Evidence |
|---|---|
| `src/aguayluz/` (23 files, 3,424 LOC) | domain engine; `aguayluz` console entrypoint via `aguayluz.cli:app` |
| `server/backend/main.py` (631 LOC) | 25 routes — `/assets`, `/assets/{id}`, `/assets/{id}/events`, `/assets.geojson`, `/municipios.geojson`, `/municipios/{name}/summary`, `/events/stream` (SSE), `/events/{id}`, `/review-queue/*`, `/notify`, `/ai/query`, `/admin/run-export`. The largest domain API in the federation. |
| Real data ingest | power / PREPA / water sources wired; `ready_for_hub_live_execution: true`, operator-approved |
| `dashboard/` (11 pages, 4,363 LOC) | Overview, Map, Assets, Outages, Monitoring, Analytics, Review, LiveLogs, and three detail pages |
| CI | `validate.yml`, `refresh.yml`, `maintenance.yml`, `centinelas-intake.yml`, `centinelas-handoff.yml`, `template-drift.yml`, `desktop-build.yml` |

**FUNCTIONAL**

| Module | Gap |
|---|---|
| `dashboard/` | no test runner in `package.json`; 0 frontend tests for 4.4k LOC |
| `scripts/` (31 files) | proportionate here, unlike the script-heavy sibling repos |
| `/ai/query` endpoint | present and wired to the UI; no dedicated test module found |

**SCAFFOLD**

| Item | Why |
|---|---|
| `dashboard/src/lib/snapshot.json` | empty `{}` — `npm run build:export` produces an offline bundle with no data. `ovnis-pr` ships a populated 1.5 MB snapshot as a working example. |
| Empty-state coverage | 1 empty-state usage across 11 pages; most tables have no designed "no rows" surface |

**DEAD** — none found. This repo ships **no auth UI at all**, which is the honest posture
given that its backend implements no authentication. Three sibling repos ship login screens
that cannot authenticate; this one does not, and that is to its credit.

Its backend does expose `GET /auth/status` — a third auth shape in the federation
(`thehub-pr`/`skywatcher-pr` use `/api/auth/me`, `centinelas-pr` uses none). Nothing in the
UI calls it.

---

## UI feature matrix

| Page | Backing endpoint | States handled | Verdict |
|---|---|---|---|
| OverviewPage | `/stats`, `/assets` | loading, error | **Production** |
| MapPage | `/assets.geojson`, `/municipios.geojson` | loading | **Production** |
| AssetsPage, AssetDetail | `/assets`, `/assets/{id}` | loading, error | **Production** |
| OutagesPage | `/events` | loading | **Production** (snapshot-grade granularity, correctly caveated) |
| MonitoringPage, LiveLogsPage | `/events/stream` (SSE) | loading | **Production** |
| AnalyticsPage | `/stats` | loading | **Functional** |
| ReviewPage | `/review-queue/*` | loading, error | **Functional** |
| MunicipioDetailPage, SectorDetailPage, EventDetailPage | detail endpoints | loading | **Functional** |

Every page maps to a real endpoint that returns real data. That is not true of any other
producer in the federation.

---

## No fixes applied in this PR

The federation-wide fixes in this audit round do not apply here:

- **Dead auth routes** — this repo has no auth UI to gate.
- **Unauthenticated entity writes** — this repo implements a domain REST API, not the generic
  `/api/entities` store, so the write-guard change made in `thehub-pr` and `skywatcher-pr`
  has no counterpart here. Its 6 mutating routes (`/notify`, `/admin/run-export`,
  `/review-queue/*`) are worth a follow-up review in their own right — see backlog item 3.
- **Documentation drift** — checked, none found.

This PR therefore adds the audit document only. Baseline recorded for future comparison:
`306 passed` (31.5s); `ruff check .` clean; `npm ci && npm run lint && npm run build` all
clean (1.8 MB JS).

---

## Backlog, ranked

| # | Item | Effort | Why it matters |
|---|---|---|---|
| 1 | Add a frontend test runner and smoke tests | **M** | 4.4k LOC of UI across 11 pages, zero tests. Copy the vitest + Testing Library setup from `thehub-pr/server/frontend`. |
| 2 | Add empty-state components | **S** | 1 empty state across 11 pages. The `ErrorBoundary` coverage here is already the best in the federation — empty states are the missing half. |
| 3 | Review authorization on the 6 mutating routes | **M** | `/admin/run-export` and `/notify` accept unauthenticated calls. `thehub-pr` and `skywatcher-pr` adopted a `PRII_WRITE_TOKEN` bearer-or-loopback guard in this same audit round; the same pattern would transfer, adapted to this repo's domain routes. |
| 4 | Populate `dashboard/src/lib/snapshot.json` | **S** | Currently `{}`, so offline export builds carry no data. |
| 5 | Raise `aria-*` coverage and add an a11y test | **M** | 11 `aria-*` and 1 `role=` across 11 pages is thin for a monitoring UI with maps and live logs. `thehub-pr` has a working `vitest-axe` gate to copy. |
| 6 | Resolve the MiLUMA data-sharing gap for outage granularity | **L** | Named in `federation.json`; external dependency, tracked honestly. |
| 7 | Decide whether `GET /auth/status` should exist | **S** | Unused by the UI and a third auth shape in one federation. Either wire it or drop it. |
