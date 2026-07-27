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
| D3 | UI craft | **4** | 11 pages, 4.4k LOC, 5 `ErrorBoundary` (most in the federation), 16 loading states, and designed empty states throughout — a shared `components/common/PanelState.jsx` plus per-view branches in `AssetsTable`, `OutagesPanel`, `MonitoringCharts`, `ReviewPage`, `OverviewPage`, `MunicipioDetailPage` and `SectorDetailPage`. Thin only on `aria-*` (11). |
| D4 | Test coverage | **4** | `306 passed` (31.5s), 32 test files against 14.0k LOC — a strong ratio |
| D5 | Engineering hygiene | **4** | `ruff check .` clean on the **widest rule set in the federation** (`E,F,I,B,UP,SIM,W`); the only producer that already ships optional write auth (`API_SECRET_KEY` via `_require_key`) |
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
| `server/backend/main.py` (631 LOC) | 25 routes — `GET /assets`, `GET /assets/{id}/events`, `PATCH /assets/{id}`, `/assets.geojson`, `/municipios.geojson`, `/municipios/{name}/summary`, `/events/stream` (SSE), `/events/{id}`, `/review-queue/*`, `/notify`, `/ai/query`, `/admin/run-export`. The largest domain API in the federation. |
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
| `dashboard/src/lib/snapshot.json` | empty `{}`, and unlike `moneysweep-pr` this repo's `build:export` does **not** run a snapshot generator first — so an offline export bundle really does ship with no data |
| Write-auth wiring | `_require_key` guards five of the six mutating routes — `POST /ai/query` (`:413`) is unguarded — and no client sends the header, so with `API_SECRET_KEY` set the five guarded actions 401 from the UI while the unguarded one keeps working |

**DEAD** — none found. This repo ships **no auth UI at all**, which is the honest posture
given its backend model. Three sibling repos ship login screens that cannot authenticate;
this one does not, and that is to its credit.

It also exposes `GET /auth/status` — a third auth shape in the federation
(`thehub-pr`/`skywatcher-pr` use `/api/auth/me`, `centinelas-pr` uses none). Nothing in the
UI calls it.

---

## UI feature matrix

| Page | Backing endpoint | States handled | Verdict |
|---|---|---|---|
| OverviewPage | `/stats`, `/assets` | loading, error | **Production** |
| MapPage | `/assets.geojson`, `/municipios.geojson` | loading | **Production** |
| AssetsPage | `/assets` | loading, error, empty | **Production** |
| AssetDetail (panel, not a route) | populated from the `/assets` collection; fetches `/assets/{id}/events` | loading, error | **Production** — note there is no `GET /assets/{id}` endpoint and no `/assets/:id` route; this is a detail panel, not a page |
| OutagesPage | `/events` | loading, empty | **Production** (snapshot-grade granularity, correctly caveated) |
| MonitoringPage, LiveLogsPage | `/events/stream` (SSE) | loading | **Production** |
| AnalyticsPage | `/stats` | loading | **Functional** |
| ReviewPage | `/review-queue/*` | loading, error | **Functional** |
| MunicipioDetailPage, SectorDetailPage, EventDetailPage | detail endpoints | loading | **Functional** |

Every page maps to a real endpoint that returns real data — the one caveat being AssetDetail,
which is a panel over the `/assets` collection rather than a routed page with its own
endpoint. No other producer in the federation comes close to this coverage.

---

## No fixes applied in this PR

The federation-wide fixes in this audit round do not apply here:

- **Dead auth routes** — this repo has no auth UI to gate.
- **Unauthenticated entity writes** — this repo implements a domain REST API, not the generic
  `/api/entities` store. It also already has the guard: `_require_key` (`server/backend/main.py:78`)
  implements optional `API_SECRET_KEY` bearer auth, and it is attached to **five of the six**
  mutating routes — `patch_asset` (`:190`), `patch_event` (`:263`), `review_decision` (`:364`),
  `run_export` (`:396`) and `notify` (`:593`). This repo got there first. Two gaps remain:
  `POST /ai/query` (`:413`) is **not** guarded (see backlog item 1), and no client sends the
  header (see backlog item 4).

  **Correction (2026-07-27).** An earlier revision of this document claimed `_require_key`
  was attached to "every mutating route" while naming only five. Re-verified by parsing each
  `@app.post`/`@app.patch` decorator against its handler signature: six mutating routes exist,
  five carry `Depends(_require_key)`, and `POST /ai/query` does not.
- **Documentation drift** — checked, none found.

This PR therefore adds the audit document only. Baseline recorded for future comparison:
`306 passed` (31.5s); `ruff check .` clean; `npm ci && npm run lint && npm run build` all
clean (1.8 MB JS).

---

## Backlog, ranked

| # | Item | Effort | Why it matters |
|---|---|---|---|
| 1 | Guard `POST /ai/query` with `_require_key` | **S** | The one mutating route without the guard (`server/backend/main.py:413`), and the one where an open door costs money: it forwards the caller's prompt to `api.anthropic.com` on the operator's `ANTHROPIC_API_KEY`. Anyone who can reach the port can spend that key. It is a one-line change — but it must land **with** item 4, or turning on `API_SECRET_KEY` breaks the dashboard's AI panel, which today works precisely because the route is open. |
| 2 | Add a frontend test runner and smoke tests | **M** | 4.4k LOC of UI across 11 pages, zero tests. Copy the vitest + Testing Library setup from `thehub-pr/server/frontend`. |
| 3 | Populate `dashboard/src/lib/snapshot.json` | **S** | Currently `{}`, and `build:export` has no snapshot-generation step, so offline bundles ship empty. `moneysweep-pr` solves this with a `snapshot` script chained into `build:export`; `ovnis-pr` ships a populated 1.5 MB file. |
| 4 | Send the `API_SECRET_KEY` bearer header from the dashboard | **M** | `_require_key` protects five of the six mutating routes, but `dashboard/src/` sends no `Authorization` header — so enabling `API_SECRET_KEY` silently breaks asset edits, review decisions, exports and notifications in the UI. This is the same client-credential gap that `thehub-pr` and `skywatcher-pr` hit with `PRII_WRITE_TOKEN` in this audit round, so it wants **one federation-wide answer**, not three local patches. |
| 5 | Raise `aria-*` coverage and add an a11y test | **M** | 11 `aria-*` and 1 `role=` across 11 pages is thin for a monitoring UI with maps and live logs. `thehub-pr` has a working `vitest-axe` gate to copy. |
| 6 | Resolve the MiLUMA data-sharing gap for outage granularity | **L** | Named in `federation.json`; external dependency, tracked honestly. |
| 7 | Decide whether `GET /auth/status` should exist | **S** | Unused by the UI and a third auth shape in one federation. Either wire it or drop it. |

---

## Maturity score — 70%

Measured 2026-07-27 against 20 explicit criteria (5 points each, 100 total). Every
lost point is a specific, verifiable work item, so this doubles as the roadmap.

| Dimension | Score | Criteria (5 pts each) |
|---|---|---|
| Functional completeness | **20/20** | backend serves domain · no dead UI · entrypoints work · modules wired, no duplicate mass |
| Data reality | **15/20** | real non-synthetic dataset · refresh automated · offline bundle populated · live-exec gate open |
| UI craft | **15/20** | pages proportionate to backend · loading+empty+error everywhere · a11y markup **and** automated gate · single consolidated frontend |
| Tests | **5/15** | suite green · coverage gate enforced · frontend tests run in CI |
| Hygiene | **4.5/15** | linters gated in CI · type checking gated in CI · write surface secured *and* client can use it |
| Docs | **10/10** | docs match code · declared status matches observed maturity |
| **Total** | **69.5/100** | |

### How the score is computed

20 criteria, 5 points each, 100 total. **Partial credit is allowed** where a criterion
splits cleanly into independent halves — for example "linters gated in CI" scores 2.5 for
Python and 2.5 for JavaScript, so a repo that gates one and not the other scores 2.5. That
is why dimension totals are not always multiples of five.

Components here sum to **69.5** (20 + 15 + 15 + 5 + 4.5 + 10), reported as **70%**. Half-points are
rounded **half up** to the nearest whole percent for the cross-repo table; the exact figure is the one
above.

The earlier 0–4 per-dimension scorecard above is retained for cross-repo comparison,
but it saturates — `aguayluz-pr` scored 24/24 on it while still having no frontend
tests. This finer model is the one to plan against.
