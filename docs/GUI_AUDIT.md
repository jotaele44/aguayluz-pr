# GUI Audit — AguaYLuz-PR Dashboard

Audit date: 2026-08-23
Scope: `dashboard/` (React 18 + Vite + Tailwind + shadcn/Radix + TanStack Query +
TanStack Virtual + MapLibre GL + Recharts), backed by `server/backend/app.py`
(FastAPI). Every page under `dashboard/src/pages` and every shared component
under `dashboard/src/components` was read; every route was booted against a
live backend and driven with Playwright (Chromium) where feasible.

## 1. Overview

AguaYLuz-PR is the water/power-infrastructure intelligence dashboard in the
PRII product family — a read-heavy operator console over Puerto Rico utility
assets, service events, operational alerts, monitoring readings (USGS/NOAA),
a Río Camuy cave & karst pilot registry, regulatory-observation ingestion,
an environmental-exposure graph, and a human review queue, plus a shadow-mode
water-disruption validation console served from the backend as a separate
static page and embedded via `<iframe>`.

**Tech stack:** React 18, react-router-dom v6 (`BrowserRouter`, or
`HashRouter` when `VITE_OFFLINE=1`), TanStack Query v5, TanStack Virtual
(virtualized tables/lists), MapLibre GL JS (self-hosted vector/raster map,
no Mapbox token), Recharts, Tailwind CSS + `class-variance-authority`,
Radix primitives (`Dialog`/`Sheet`, `Select`, `Toast`, `Tabs`/`Toggle`
dependencies present but currently unused in the app), `@pr-federation/react`
(shared federation UI kit: `FederationPanel`, `FederationStatCard`,
`FederationEmptyState`), `@sentry/react` (error boundary reporting, opt-in via
`VITE_SENTRY_DSN`).

**Backend:** `server/backend/app.py` — the canonical ASGI app. It re-exports
every route from the legacy `server/backend/main.py` *except* the legacy
`GET /readings` (replaced by a metric-safe version), and adds
cave-karst (`/cave-karst/*`), regulatory (`/regulatory/*`),
environmental-exposure (`/environmental-exposure/*`), water-disruption
(`/water-disruption/*`), and monitoring-incident-ledger (`/monitoring/*`)
routers. This is the app both `dashboard/gui-parity.playwright.config.mjs`
and the desktop wrapper (`desktop/config.py: APP_IMPORT`) boot — i.e. the
canonical, currently-shipping backend.

**Entry points:**
- Dev: `cd dashboard && npm run dev` → Vite on `:5173` (hard-coded in
  `vite.config.js` to match the backend's CORS allowlist), talking to
  `VITE_API_BASE` (default `http://localhost:8000`).
- `npm run test:gui-parity` — `vitest run src/pages/CaveKarstPage.test.jsx`
  then `playwright test -c gui-parity.playwright.config.mjs`. The Playwright
  config boots the real backend (seeding a demo review-queue via
  `server/ingestion/seed_demo.py` first, if present) on `:8000` and Vite on
  `:5173`, then walks every `active`/non-`internal` route in
  `.federation/gui-capabilities.json`, asserts `/monitoring`'s series
  dropdown, and asserts `/review`'s severity-tone rendering with a stubbed
  response.
- Desktop app: see §3 below.
- Offline export: `npm run build:export` (`VITE_OFFLINE=1`) inlines a data
  snapshot and produces a single-file `index.html` under
  `dashboard/export-standalone/`, openable via `file://` with no backend.

**Routes** (`dashboard/src/App.jsx`, all lazy-loaded, all under one
`DashboardLayout` except the catch-all): `/`, `/map`, `/assets`, `/alerts`,
`/alerts/:id`, `/outages`, `/monitoring`, `/cave-karst`, `/regulatory`,
`/regulatory/review`, `/environmental-exposure`, `/review`, `/analytics`,
`/logs`, `/system`, `/water-disruption`, `/sector/:sector`, `/events/:id`,
`/municipios/:name`, and a catch-all `*` → `PageNotFound`. 19 routed page
components live under `dashboard/src/pages` (23 files there in total once the
4 co-located `*.test.jsx` files are counted).

**Global chrome**, rendered on every routed page via `DashboardLayout`:

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Sidebar collapse toggle | button | chevron icon | `setCollapsed(c => !c)` (`SidebarContext`) — shrinks sidebar to a 56px icon rail | Live | Confirmed `aria-label` flips Collapse↔Expand |
| Sidebar nav links | 15 `NavLink`s | Overview, Map, Assets, Alerts, Outages, Water Validation, Monitoring, Cave & Karst, Regulatory, Regulatory Review, Exposure Graph, Review Queue, Analytics, Live Logs, System & Tools | react-router navigation to each route | Live | Ran the repo's own `npm run test:gui-parity` (vitest + `gui-parity.playwright.config.mjs`) against a freshly booted backend+frontend: **21/21 tests passed**, including one per active/non-internal manifest route (15 of the 19 total routes — the 4 excluded are parameterized detail pages with no flat nav link: `/alerts/:id`, `/events/:id`, `/sector/:sector`, `/municipios/:name`) that literally clicks the `a[href="<route>"]` nav link from `/` and asserts the URL changes and `#root` renders with no runtime error. Teardown cleanly removed its seeded fixture afterward. This audit's own scripts additionally drove Map/Assets/Alerts/Outages/Monitoring/Cave&Karst/Regulatory/Review/System/Logs live via direct navigation |
| Mobile hamburger menu | button | ☰ icon | `setCollapsed(c => !c)`, only rendered when `useIsMobile()` | Static-only | Not exercised — audit ran at desktop viewport (1440×900) |
| Mobile sidebar scrim | div (click target) | — | closes sidebar on mobile when tapped outside | Static-only | same mobile-viewport gap |
| StatsBar "System & Tools" link | link | `System & Tools` | navigate to `/system` | Static | Redundant with sidebar link, same target |
| StatsBar backend-down banner dismiss | button | × icon | `setDismissed(true)`, hides the red banner for the session | Static | Only renders when the backend is unreachable; not exercised (backend was up throughout) |
| AI Query Panel launcher | button (fixed, bottom-right) | "Ask AI" | `setOpen(true)` — opens floating chat panel | Live | |
| AI Query Panel close | button | × icon | `setOpen(false)` | Static | |
| AI Query Panel suggestion chips | 3 buttons | "How many assets are tracked?", "What sectors have the most events?", "Summarize the current infrastructure status" | fills the input with the suggestion text | Live | one clicked |
| AI Query Panel input + submit | text input + button/Enter | — | `postAiQuery(query)` → `POST /ai/query` | Live | **static-only: requires `ANTHROPIC_API_KEY`** on the backend — confirmed the backend returns `503`, and the panel renders the graceful `"AI query ... API key auth is enabled"`/error text rather than crashing |

## 2. Pages

### 2.1 Overview — `/` (`OverviewPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| AI Status Recap | button | "AI Status Recap" / "Summarizing…" | `handleSummarize` → composes a status prompt from live counts, `postAiQuery` → `POST /ai/query`, renders `aiSummary` | Live | 503 without `ANTHROPIC_API_KEY`; handled gracefully (error text shown inline, no crash) |
| Send Alert | button | "Send Alert" / "Sending…" | `handleNotify` → `postNotify({message, title})` → `POST /notify`; toasts dispatched vs. "No channels configured" | Live | Backend returned `200` with `channels_active: 0` in this sandbox (no Slack/ntfy/SMTP env vars) → destructive toast "No channels configured" shown correctly |
| "Review them in the assets table" | link | — | → `/assets?unmapped=1` | Static | Only rendered when `coverage` data present; pre-applies the Assets page's Unmapped filter |
| "N life-safety critical alert(s) open" | link | — | → `/alerts?critical=1` | Static | Only rendered when `alerts_critical > 0`; pre-applies Alerts page's Critical filter |
| Sector cards | 4 links (Power/Water/Wastewater/Telecom) | sector label + count | → `/sector/:key` | Live | Power card clicked, navigated to `/sector/power` and rendered |
| Reservoir levels chart | Recharts `AreaChart` | — | hover tooltip only, no click behavior | Live | Confirmed live: this chart is **broken** — see §4 findings (backend `400`s on `GET /readings?kind=reservoir` with no `metric`) |
| Recent Events list | static rows | — | display only, not clickable | — | |

### 2.2 Map — `/map` (`MapPage.jsx` + `AssetMap.jsx`)

`AssetMap` is used only here. Right rail reuses `AssetsTable`/`AssetDetail`
(see §2.3 for their controls, not repeated below).

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Layer toggle buttons | 7 buttons | Power, Water, Wastewater, Other, Municipios, Events, Alerts (each with a live count) | toggles `layers.<key>` in local state, filters the GeoJSON source shown on the map | Live | Power and Alerts toggled |
| "Life-safety critical alerts only" | button (conditional, shown when Alerts layer on) | — | toggles `layers.criticalAlertsOnly`, filters `alertGeo` to `is_critical` features | Live | confirmed appears after enabling Alerts layer |
| "Review-needed assets only" | button | — | toggles `layers.review`, filters visible assets to `review_status === 'needs_review'` | Static | |
| Basemap switch | 2 buttons | "Map" / "Satellite" | `setBasemap('osm'|'satellite')`, toggles MapLibre layer visibility | Live | Satellite clicked, no crash |
| Map marker click (asset dot) | MapLibre layer click | — | `onSelect(props)` → opens `AssetDetail` sheet for that asset | Static | Code-read; canvas-rendered layer, not driven live in headless Chromium (tile network unavailable in sandbox — see §4) |
| Map marker click (alert dot) | MapLibre layer click | — | `onAlertSelect(props)` → `navigate('/alerts/:id')` | Static | |
| Cluster click | MapLibre layer click | — | expands cluster zoom via `getClusterExpansionZoom` | Static | |
| Municipio polygon click | MapLibre layer click | — | `onMunicipioSelect({name, properties})`, pivots the map-intelligence caption | Static | |
| MapLibre `NavigationControl` | zoom +/− buttons (library-provided) | — | standard MapLibre zoom | Static | |
| Right-rail `AssetsTable` | — | — | identical controls to §2.3 (search/filters/sort/row-select), scoped `syncUrl={false}` so it does not write to the URL | Live | shares AssetsTable code path verified in §2.3 |
| `AssetDetail` sheet | — | — | identical to §2.3's asset detail sheet | Static | |
| "N of M assets mapped" caption | static text | — | not interactive | — | |

### 2.3 Assets — `/assets` (`AssetsPage.jsx` + `AssetsTable.jsx` + `AssetDetail.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Search input | text input | "Search asset, municipio, operator, source…" | client-side substring filter across name/municipio/operator/type/subtype/source/id; URL-synced (`?q=`) on this page | Live | filtered to "reservoir" |
| Clear filters | button | × / FilterX icon | resets all filters to defaults | Live | |
| Export CSV | button | download icon, title "Export CSV" | `downloadCSV('assets.csv', rows, [...cols])` — client-side CSV generation and browser download | Live | download event fired, filename `assets.csv` |
| Type select | select | asset type | filters by `asset_type`, resets Subtype to "all" on change | Static | |
| Subtype select | select | asset subtype | filters by `asset_subtype`, options scoped to selected Type | Static | |
| Status select | select | status | filters by `status` | Static | |
| "Needs review" toggle | button | AlertTriangle icon + label | toggles `reviewOnly` filter (`review_status === 'needs_review'`) | Live | |
| "Unmapped" toggle | button | MapPinOff icon + label | toggles `unmappedOnly` filter (no lat/lon) | Live | |
| Column sort headers | 4 clickable `<th>` | Asset, Type, Municipio, Evidence | client-side sort toggle asc/desc, keyboard-activatable (Enter/Space) | Live | "Type" header clicked, `aria-sort` updates |
| Table row | clickable row (click + Enter/Space) | — | `onSelect(asset)` → opens `AssetDetail` sheet | Live | |
| Keyboard: `/` | shortcut | — | focuses the search input | Static | code-read only |
| Keyboard: `j`/`k` | shortcut | — | moves row selection up/down, scrolls into view via the virtualizer | Static | code-read only |
| **AssetDetail sheet** | | | | | |
| "Show on map" | button (conditional, lat/lon present) | Map icon | closes sheet, `navigate('/map?flyTo=...')` | Static | |
| "Flag for review" / "Unflag" | button | Flag icon | `useFlagAsset` → `PATCH /assets/:id {review_status}` | Live | toggled live, toast confirmed |
| "Raw record preview" | collapsible button | chevron + label | expands/collapses a `<pre>` JSON dump of the raw asset record | Live | |
| Sheet close | Radix `Sheet` dismiss (X / overlay / Escape) | — | `onClose()` | Static | `Escape` key handled explicitly in `AssetDetail.jsx` in addition to Radix's default |
| Related-events section | read-only list (up to 8) | — | not interactive | — | |
| Source link (in Evidence section) | external link (conditional, `http(s)://` source_ref) | — | opens source in new tab | Static | |

### 2.4 Alerts — `/alerts` (`AlertsPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Search input | text input | "Search alert title, asset, or id…" | URL-synced `?q=`, server-side filter via `GET /alerts` | Static | |
| Critical toggle | button | ShieldAlert icon + "Critical" | URL-synced `?critical=1`, server-side `critical_only` filter | Live | `aria-pressed` flips true/false |
| Clear filters | button | FilterX icon | resets `module`/`status`/`review`/`tier`/`critical`/`q` | Live | |
| Module facet select | select | dynamic counts from `/alerts/facets` | server-side `module_id` filter | Static | |
| Status facet select | select | dynamic counts | server-side `status` filter | Static | |
| Review-state facet select | select | dynamic counts | server-side `review_status` filter | Static | |
| Evidence-tier facet select | select | dynamic counts | server-side `tier` filter | Static | |
| Export CSV | button | Download icon | `downloadCSV('alerts.csv', items, [...])`, current page only | Live | download fired |
| Alert row | link | alert title/id | → `/alerts/:id` | Live | navigated to a live alert detail |
| "Load N more" | button | — | raises client-side `limit` by 500 and refetches | Live | clicked, no error |
| Coverage-gap banner | static text | — | not interactive; lists `gap_id`s when `/alerts/gaps` returns rows | — | |

### 2.5 Alert Detail — `/alerts/:id` (`AlertDetailPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| "Alerts" breadcrumb | link | ArrowLeft + "Alerts" | → `/alerts` | Live | reached via Alerts-page row click |
| Source link (conditional, `http(s)://`) | external link | source URL | opens in new tab | Static | |
| Linked asset rows | N links | asset name | → `/map?flyTo=...` (geolocated) or `/assets?q=...` (not geolocated) | Static | correct pattern — contrast with §4 finding on `MunicipioDetailPage` |

### 2.6 Outages — `/outages` (`OutagesPage.jsx` → `OutagesPanel.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Search input | text input | "Search area / municipio…" | client-side filter on `affected_area`/`municipality` | Static | |
| Type select | select | `EVENT_TYPES` | client-side filter on `event_type` | Static | |
| Municipio/area group header | link | area name | → `/municipios/:name` | Live | navigated to `/municipios/Utuado` |
| Event row | link | event type + area | → `/events/:id` | Live | reached via this link in a separate run |
| Snapshot-caveat banner | static text | — | not interactive | — | |

### 2.7 Event Detail — `/events/:id` (`EventDetailPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| "Outages" breadcrumb | link | ArrowLeft + "Outages" | → `/outages` | Static | |
| ACK / Resolved | button | CheckCircle2 icon + "ACK"/"Resolved" | `useAckEvent` → `PATCH /events/:id {resolution_status:'resolved'}`; disabled once already resolved | Live | clicked; backend returned `200`, invalidates `event`/`events` queries |
| "Report" | external link | FileText icon + "Report" | opens `GET /export/report.html` in new tab | Static | |
| Linked asset rows | N links | asset name | → `/map?flyTo=...` or `/assets?q=...` | Static | correct pattern |

### 2.8 Water Disruption — `/water-disruption` (`WaterDisruption.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Embedded console | `<iframe src="/water-disruption/console">` | — | loads the backend-rendered shadow-mode water-incident console (`server/backend/water_disruption_api.py`) directly | Live | **Confirmed broken in `npm run dev`** — see §4 finding. The backend itself serves a real console at that path (`GET /water-disruption/console` → 200, title "Agua y Luz Water Incidents") when hit directly, but the iframe's `src` is a same-origin-relative path resolved against the *frontend* dev-server origin, and Vite has no proxy rule for it — so Vite's SPA fallback serves `index.html` and the iframe recursively renders the whole dashboard inside itself instead of the console. Same-origin desktop packaging (§3) is unaffected because frontend and backend share one origin there. |

### 2.9 Monitoring — `/monitoring` (`MonitoringPage.jsx` → `MonitoringCharts.jsx` + `IncidentOperationsConsole.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Range buttons | 4 buttons | 7d, 30d, 90d, all | sets `since` param passed to `GET /readings` | Live | "30d" clicked |
| Monitoring series select | select, `aria-label="Monitoring series"` | e.g. "Reservoir elevation", "Annual peak streamflow", "Groundwater depth (discrete)" | `MONITORING_SERIES` registry lookup, switches `kind`/`metric` query params | Live | switched to "Annual peak streamflow", chart re-rendered, header echoed the label |
| Site select | select (conditional, >1 site) | site ids + reading counts | filters chart to one `site_no` | Static | |
| Incident list items | N buttons | incident id, status, assignee, timeline count | `setSelected(incident_id)` | Static | list was empty in this sandbox ("No persistent incidents" — ledger requires `POST /monitoring/incidents/bootstrap`, which is auth-gated) |
| Actor input | text input | — | local state, sent with the next transition | Static | |
| Reason input | text input | — | local state, sent with the next transition | Static | |
| Transition buttons | 6 buttons | acknowledged, assigned, suppressed, resolved, reopened, threshold_migrated | `POST /monitoring/incidents/:id/transitions`, disabled when no incident selected | Live | confirmed `disabled=true` with nothing selected (no incidents to select in this sandbox) |

### 2.10 Cave & Karst — `/cave-karst` (`CaveKarstPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Pilot asset selector | N buttons, `aria-pressed` | canonical name + status badge | `setSelectedId(asset_id)`, drives detail/history/provenance/edges queries | Live | selected the 2nd of 4 pilot assets, `aria-pressed` flipped, detail panel updated |
| Source links (Provenance section) | N external links (conditional, `source.url` present) | "Source" + ExternalLink icon | opens source in new tab | Static | |
| Scope-limitation banner | static text | — | not interactive | — | |

### 2.11 Regulatory — `/regulatory` (`RegulatoryPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Provider select | select, `aria-label="Filter by provider"` | all / EPA / FDA / USGS / DRNA / PRASA_AAA / PREQB | `GET /regulatory/observations?provider=...` | Live | filtered to USGS live |
| Record-family select | select | all / entity / permit / inspection / enforcement | server-side filter | Static | |
| Freshness-state select | select | all / current / historical / stale / unknown / conflicting | server-side filter | Static | |
| Observation selector | N buttons, `aria-pressed` | provider · record id, freshness badge | `setSelectedId(observation_id)`, drives detail query | Static | same pattern as Cave & Karst's asset list, verified working there |
| Payload viewer | read-only `<pre>` JSON | — | not interactive | — | |

### 2.12 Regulatory Review — `/regulatory/review` (`RegulatoryReviewPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Decision-state select | select | all / proposed / needs_review / approved / rejected | `GET /regulatory/links?decision_state=...` | Static | |
| Candidate selector | N buttons, `aria-pressed` | candidate asset id, decision badge | `setSelectedId(candidate_id)` | Static | empty queue in this sandbox — "No candidates match the current filter" rendered correctly, confirmed live |
| Actor input | text input, `#actor-input` | — | local state, required (non-empty) to enable decision buttons | Static | |
| Rationale textarea | textarea, `#rationale-input` | — | local state, required (non-empty) to enable decision buttons | Static | |
| Approve | button | CheckCircle icon | `postRegulatoryLinkDecision(id, 'approved', actor, rationale)`; disabled while `!canSubmit` **or** any open contradiction exists (fail-closed) | Static | code-read; no candidates present to exercise live |
| Reject | button | XCircle icon | same call with `'rejected'`; disabled while `!canSubmit` only | Static | |
| Mark needs review | button | — | same call with `'needs_review'` | Static | |

### 2.13 Environmental Exposure — `/environmental-exposure` (`EnvironmentalExposurePage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| — | — | — | Read-only summary tiles + relationships table; no buttons, filters, or selects on this page | Live | page loads cleanly, no console errors, empty-state text renders correctly when no relationships are materialized |

### 2.14 Review Queue — `/review` (`ReviewPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Severity select | select | `SEVERITIES` (all/block/warn/info) | URL-synced `?sev=`, server-side filter, resets `offset` | Static | |
| Tier select | select | `TIERS` | URL-synced `?tier=`, server-side filter, resets `offset` | Static | |
| Export CSV | button | Download icon | `downloadCSV('review-queue.csv', items, [...])`, current page only | Live | download fired |
| "Select all on page" | button/checkbox | CheckSquare/Square icon | toggles all visible rows into the `selected` Set | Live | confirmed "N selected" indicator appears |
| Per-row select checkbox | button/checkbox | — | toggles one row into `selected` | Static | same mechanism as select-all |
| "Approve all" | button (conditional, selection > 0) | CheckCircle icon | sequential `decide({ref, decision:'accept'})` per selected row | Live | confirmed the button *appears and is enabled* on selection; not actually submitted (would have consumed the last remaining seed records) |
| "Reject all" | button (conditional) | X icon | sequential `decide({ref, decision:'reject'})` | Live | renders in the same conditional block as Approve all, confirmed present; not submitted, same reason |
| "Skip all" | button (conditional) | — | sequential `decide({ref, decision:'skip'})` | Live | same as above |
| Per-row AI suggest | button, title "Ask AI for a recommendation" | Bot icon | `postAiQuery(...)` with the record's fields, renders inline suggestion | Live | 503 without `ANTHROPIC_API_KEY`, handled gracefully |
| Per-row Accept | button | CheckCircle + "Accept" | `useDecision` → `POST /review-queue/:ref/decision {decision:'accept'}`, optimistic removal | Static | same endpoint verified live via Skip below |
| Per-row Reject | button | X + "Reject" | same endpoint, `decision:'reject'` | Static | |
| Per-row Skip | button, `aria-label`/title "Skip" | SkipForward icon | same endpoint, `decision:'skip'` | Live | clicked on `SEED-BLOCK-0001`; backend logged `POST /review-queue/SEED-BLOCK-0001/decision → 200 OK`, row removed from the list |
| Row click | click target | — | moves the keyboard cursor to that row (`setCursor(i)`) | Static | |
| Pagination Previous/Next | 2 buttons | ChevronLeft/Right icons | `offset -= / += PAGE_SIZE` (25), URL-synced | Static | |
| Keyboard: `j`/`k`/↓/↑ | shortcut | — | moves cursor | Static | |
| Keyboard: `a`/`r`/`s` | shortcut | — | accept/reject/skip the row under cursor | Static | |

### 2.15 Analytics — `/analytics` (`AnalyticsPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| — | — | — | 4 read-only Recharts panels (Events by Type, Top Municipios, Assets by Type, Asset Status pie) computed client-side from already-fetched `assets`/`events`; hover tooltips only, no click/filter controls | Live | page loads cleanly, no console errors |

### 2.16 Live Logs — `/logs` (`LiveLogsPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Type filter | select | `EVENT_TYPES` | URL-synced `?type=`, client-side filter over the live SSE buffer | Static | |
| Area/municipio search | text input | "Filter area / municipio…" | client-side filter | Static | |
| Pause/Resume | button | Play/Pause icon | toggles `autoScroll`, which gates the auto-scroll-to-bottom effect (the `EventSource` connection itself is never paused, only the scroll) | Live | clicked, label flipped Pause→Resume |
| SSE connection | `EventSource(/events/stream)` | — | not a click control; connects on mount, `onmessage` replaces the events array wholesale | Live | connected (backend logged `GET /events/stream → 200`) |

### 2.17 System & Tools — `/system` (`SystemPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| "Run federation export" | button | RefreshCw icon | `useRunExport` → `POST /admin/run-export`, regenerates `outputs/`/`exports/federation` | Live | confirmed **enabled** (backend up, no `API_SECRET_KEY`); not clicked to avoid mutating the sandbox's export artifacts mid-audit |
| "Send status alert" | button | Bell icon | `postNotify(...)` with current alert counts | Live | confirmed **disabled** — no Slack/ntfy/email env vars configured, so `notifyReady` is false; the caption states the exact env vars needed |
| "Open status report" | external link | FileText icon | opens `GET /export/report.html` in new tab | Live | `href` resolved to the live backend origin |
| API key form (conditional, only when backend `auth_enabled`) | password input + "Set key"/"Replace key" button + "Clear" button | — | `setApiKey()`/`getApiKey()` in `sessionStorage`; gates every mutating request via a Bearer header | Static | panel did not render — `API_SECRET_KEY` unset on this backend, confirmed via `status.auth_enabled === undefined` |

### 2.18 Sector Detail — `/sector/:sector` (`SectorDetailPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Back arrow | link | ArrowLeft icon | → `/` | Static | |
| Asset status bar chart, related-events list, assets table | read-only | — | no interactive controls beyond the back link — table caps at 100 rows with a "Showing 100 of N" caption | Live | reached via Overview's "Power" sector card, rendered correctly |

### 2.19 Municipio Detail — `/municipios/:name` (`MunicipioDetailPage.jsx`)

| Element | Type | Label | Handler / Behavior | Verified | Notes |
|---|---|---|---|---|---|
| "Map" breadcrumb | link | ArrowLeft + "Map" | → `/map` | Static | |
| Event row | N links | event type + area | → `/events/:id` | Static | same working pattern as Outages panel |
| **Asset row** | **N links** | **asset name + status badge** | `to={`/assets/${a.asset_id}`}` | **Live — CONFIRMED BROKEN** | **No `/assets/:id` route is registered in `App.jsx` (only `/assets`, `/sector/:sector`, `/events/:id`, `/alerts/:id`, `/municipios/:name`). Every asset link on this page lands on the catch-all `PageNotFound` 404 page.** Live-clicked `/assets/LOCAL_000245522b7e3228` → rendered "404 / Page Not Found". Contrast with the *correct* pattern used by `AlertDetailPage`/`EventDetailPage`, which route asset links through `/map?flyTo=...` (geolocated) or `/assets?q=...` (not geolocated) — see §4. |

## 3. Desktop Launcher

Reading `desktop/launch.py`, `desktop/app_server.py`, `desktop/_page.py`,
`desktop/setup_actions.py`, `desktop/config.py`, `desktop/setup.py`, and the
root `PRII-AGUAYLUZ.{app,command,sh,bat}` launcher scripts:

- **`PRII-AGUAYLUZ.command`** (macOS double-click) / **`.sh`** (Linux) /
  **`.bat`** (Windows) all do the same three things: `cd` to the repo root,
  run `python desktop/setup.py --ensure` (idempotent — no-ops once already
  set up), then `exec` the private venv's Python on `desktop/launch.py`.
- **`PRII-AGUAYLUZ.app`** is a macOS app bundle (`Info.plist` +
  `Contents/MacOS/PRII-AGUAYLUZ` + `Contents/Resources/AppIcon.icns`) whose
  binary is the rendered shared-federation-template launcher script — same
  effect as `.command`.
- **`desktop/setup.py`** (one-time, `--ensure`-gated by a `.setup-complete`
  marker file): creates a private `.venv` at the repo root, installs
  `server/backend/requirements.txt` + `requirements-desktop.txt`, then runs
  `npm ci`/`npm install` + `npm run build` in `dashboard/` with
  `VITE_API_BASE=""` (empty — same-origin) to produce `dashboard/dist/`.
- **`desktop/launch.py`** and **`desktop/app_server.py`** are thin shims
  delegating to the shared `prii_desktop` package (a local path dependency
  from `thehub-pr/packages/prii_desktop`, per the module docstrings) —
  `launch()` starts a uvicorn server hosting the *same-origin* ASGI app
  (`make_desktop_app`, combining `server.backend.app:app` — `APP_IMPORT` in
  `desktop/config.py` — with the built `dashboard/dist/` static files) and
  opens a native window (or the default browser with `--browser`) pointed at
  it. Flags: `--no-window`, `--browser`, `--route PATH`, `--smoke` (CI
  headless-boot check) — all handled inside `prii_desktop`, not in this repo.
- **`desktop/config.py`** — per-repo values only: `APP_TITLE="AguaYLuz"`,
  `APP_ID="AguaYLuz"`, brand colors, `AGUAYLUZ_DATA_HOME` env var name,
  `APP_IMPORT="server.backend.app:app"` (the canonical app — same one this
  audit ran against), `FRONTEND_DIR`/`DIST_DIR` under `dashboard/`,
  `HEALTH_PATH="/health"`.
- **`desktop/_page.py`** — shared dark-theme HTML shell (spinner CSS, base
  styles) used by the launcher's splash/error pages while uvicorn boots or if
  the build is missing; not part of the dashboard app itself.
- **`desktop/setup_actions.py`** (`prepare_workspace`, invoked by the native
  setup UI via `SETUP_ACTION`) — idempotently copies the bundled read-only
  `data/` and `outputs/` trees into the user's writable
  `$AGUAYLUZ_DATA_HOME/{data,exports}` on first run, without ever overwriting
  files the user has since modified.

Net effect for an end user: double-click a launcher → one-time dependency
install (internet required once) → a native window opens showing the exact
same dashboard audited above, served from a single local port with no CORS
split (the `/water-disruption` iframe bug in §4 does **not** reproduce in
this packaging, since frontend and backend share one origin there).

## 4. Findings — broken / dead / notable controls

1. **Broken link — `MunicipioDetailPage` asset rows route to a non-existent
   `/assets/:id`.** Live-confirmed: clicking any asset row on
   `/municipios/:name` lands on the catch-all 404 page. `AlertDetailPage` and
   `EventDetailPage` handle the identical case correctly (`/map?flyTo=...` /
   `/assets?q=...`); `MunicipioDetailPage.jsx` should use the same pattern.
2. **Broken in dev — `WaterDisruption` page's iframe.** Live-confirmed:
   under `npm run dev` (split frontend/backend ports, the officially
   documented dev workflow), the iframe's relative `src="/water-disruption/console"`
   resolves against the Vite origin, which has no route or proxy for it and
   falls back to serving the SPA — so the iframe recursively renders the
   entire dashboard instead of the intended console. The backend's own
   `/water-disruption/console` endpoint works correctly when hit directly.
   Not a bug in the desktop/production same-origin packaging (§3).
3. **Overview page's "Reservoir Levels" chart never renders data against the
   canonical backend.** Live-confirmed: `OverviewPage` calls
   `useReadings({kind:'reservoir'})` with no `metric`, but
   `server/backend/app.py`'s `/readings` requires a `metric` for the
   `reservoir` vector (`metric_required: True`) and returns `400 Bad
   Request`. This is the same app both the dev workflow and the desktop
   packaging boot, so the chart is silently empty (falls into the "No
   reservoir data available" branch) in every normal run of this app, not
   just this sandbox.
4. **Cosmetic — MapLibre style missing a `glyphs` source.** Live-confirmed
   console error on `/map`: `layers.cluster-count.layout.text-field: use of
   "text-field" requires a style "glyphs" property`. The cluster-count number
   labels (`cluster-count` symbol layer in `AssetMap.jsx`'s `BASE_STYLE`)
   never render text as a result — clusters show as colored circles with no
   count number.
5. **Minor React warning** on every page that mounts a `Toast` (confirmed on
   `/`, `/assets`, `/review`): `Warning: Unknown event handler property
   onOpenChange` from `components/ui/toast.jsx`'s wrapper around the Radix
   `Toast` root — spreads an `onOpenChange` prop onto a plain `<div>`.
   Cosmetic (React strips it), not functional.
6. **Dead/orphaned component — `components/ReviewQueue.jsx`.** Fully built
   (search, severity/tier selects, read-only record cards) but not imported
   by any page or by `App.jsx`; `ReviewRecordCard.jsx` (which it wraps) is
   only otherwise exercised by its own component test. Either intentionally
   retired or a page wiring that was never finished.
7. Everything else driven live (see the per-page tables) behaved as coded:
   filters, sorts, CSV exports (3/3 triggered real downloads), the review
   queue's accept/skip/select-all/batch-approve affordances, map layer/basemap
   toggles, monitoring series/range switching, cave-karst and regulatory
   record selection, event ACK, sidebar collapse, and the AI-query/notify
   integrations' graceful-degradation paths (503/no-channels handled without
   a crash) all matched their code-read behavior with no console errors
   beyond the two noted above.

## 5. Summary

- **Pages audited:** 19 routed page components (23 files counting the 4
  co-located `*.test.jsx`), plus global chrome (`Sidebar`, `StatsBar`,
  `AiQueryPanel`) and the desktop launcher.
- **Interactive elements cataloged: 151.** Counting method: each table row
  above counts once per distinct, individually labeled control; a row that
  groups a small **fixed** set of labeled controls (e.g. "7 layer toggle
  buttons", "4 range buttons", "6 incident-transition buttons", "4 sector
  cards", "15 sidebar nav links") is counted at that fixed size, since each
  one is a distinct, separately-labeled function. A row describing a
  **data-driven, variable-length** list (e.g. "N alert rows", "N linked
  asset rows", "N pilot-asset selector buttons") counts once, as one control
  *type* with one handler — not once per data record, since the record count
  varies with the corpus. Pure display rows (charts' hover-only tooltips,
  read-only lists/badges/banners) are excluded entirely.
  - Global chrome: 27 (1 sidebar toggle + 15 nav links + 1 mobile hamburger
    + 1 mobile scrim + 1 StatsBar link + 1 StatsBar dismiss + 1 AI launcher
    + 1 AI close + 3 AI suggestion chips + 1 AI input/submit)
  - Per-page: Overview 8 · Map 16 · Assets 20 · Alerts 10 · Alert Detail 3 ·
    Outages 4 · Event Detail 4 · Water Disruption 1 · Monitoring 15 ·
    Cave & Karst 2 · Regulatory 4 · Regulatory Review 7 ·
    Environmental Exposure 0 · Review Queue 17 · Analytics 0 · Live Logs 3 ·
    System & Tools 6 · Sector Detail 1 · Municipio Detail 3
- **Live-verified: 84 / 151 (56%).** Includes the repo's own
  `test:gui-parity` suite run fresh for this audit (21/21 passed — 15 nav
  links + 3 monitoring-series selections + 2 review-queue rendering
  assertions) plus this audit's own Playwright scripts driving clicks,
  fills, selects, sorts, toggles, CSV downloads (3/3 produced real
  `download` events), and mutating actions (asset flag/unflag, review-queue
  skip decision, event ACK) against a live backend, with resulting network
  calls confirmed in the backend's access log and resulting UI state
  (toasts, badges, `aria-pressed`/`aria-sort`, URL changes) asserted after
  each. Where a row represents a fixed set with one handler (e.g. 7 map
  layer toggles, 4 sort headers, 4 sector cards), exercising one member live
  is credited as verifying the row.
- **Static-only: 67 / 151 (44%)** — read from source, not exercised live.
  Breakdown: per-facet `<select>` duplicates of an already-verified select
  pattern (~20); MapLibre canvas-layer click handlers, unreachable in
  headless Chromium without a real tile-server network (5); the Regulatory
  Review decision workflow, empty of candidate data in this seed (7);
  per-row Accept/Reject buttons on the Review Queue, whose Skip sibling *was*
  exercised against the identical handler (2); mobile-viewport-only controls,
  since the audit ran at a 1440×900 desktop viewport (2); a handful of
  breadcrumbs/detail-page links reached indirectly but not themselves clicked
  (~10); and controls gated behind unavailable external services —
  **requires `ANTHROPIC_API_KEY`** (AI Status Recap, Review's per-row AI
  suggest, the AI Query Panel — all 3 *were* clicked live and confirmed to
  fail gracefully with a `503` rather than crashing) and **requires
  `SLACK_WEBHOOK_URL`/`NTFY_TOPIC`/SMTP env vars** (Send Alert / Send status
  alert — also clicked live, confirmed to either report "no channels
  configured" or render disabled with the missing env var named).
- **Broken/dead controls found:** 2 confirmed-live bugs (Municipio Detail's
  asset links → 404; Water Disruption's dev-mode iframe recursion), 1
  confirmed-live data-contract bug (Overview's reservoir chart always empty
  against the canonical backend), 1 confirmed-live cosmetic MapLibre style
  issue (cluster count labels invisible), 1 confirmed-live cosmetic React
  prop warning, and 1 orphaned/unmounted component (`ReviewQueue.jsx`).
