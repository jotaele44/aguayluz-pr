# Accessibility Audit — AguaYLuz-PR Dashboard

Audit date: 2026-08-24
Scope: `dashboard/` (React 18 + Vite + Tailwind + shadcn/Radix + MapLibre GL),
backed by `server/backend/app.py` (FastAPI), the same canonical stack
documented in `docs/GUI_AUDIT.md` (Phase 1). This is the Phase 2
federation-wide audit: accessibility (axe-core, keyboard, touch targets,
overflow) plus a design-system-usage inventory (`docs/design-system-usage.json`).

## 1. Overview

Five real, in-app routes were live-scanned at two viewports using axe-core
against a real backend (19,723 assets / 26,554 events / 4,339 alerts, the
repo's actual working data — not a synthetic seed). The app ships **no light
theme** — `dashboard/src/index.css` defines a single `:root` dark palette
with no `.light`/`prefers-color-scheme` override and no theme toggle exists
anywhere in the UI (see `docs/design-system-usage.json`) — so every scan
below is inherently a dark-theme-only result; there is no second theme to
compare against.

Headline results:
- **0 routes are fully clean.** Every one of the 5 scanned routes fails at
  least the touch-target-minimum check at both viewports, and 4 of 5 fail
  axe critical/serious checks at one or both viewports.
- **1 critical, repo-wide bug**: the mobile hamburger menu button
  (`dashboard/src/components/layout/DashboardLayout.jsx`) is icon-only with
  no accessible name — axe's `button-name` (critical) fires on every route at
  the 390px viewport.
- **1 critical, page-specific bug**: `ReviewPage`'s severity/tier `<Select>`
  triggers (`dashboard/src/pages/ReviewPage.jsx:167-174`) have no
  accessible name at **either** viewport, despite visibly showing "all" —
  see §4 finding 2 for why the visible text doesn't count.
- **1 confirmed-live, non-axe usability blocker**: at a 390px viewport the
  sidebar renders *open* on first paint and its dismiss scrim sits above the
  header bar, so the hamburger button that is supposed to close it is itself
  pointer-blocked on load (§4 finding 3).
- **Systemic `color-contrast` (serious)** and **touch-target-minimum**
  failures recur on nearly every route — these are design-token-level
  issues (Tailwind `slate-500`/`slate-600` text color, and small icon/chip
  buttons throughout), not one-off mistakes.

## 2. Method

- **Backend**: `server/backend/app.py` (FastAPI/uvicorn) on
  `127.0.0.1:8107`. Boot command:
  `PYTHONPATH="$(pwd)/src:$(pwd)" ALLOWED_ORIGINS="http://localhost:5307,http://127.0.0.1:5307" python3 -m uvicorn server.backend.app:app --host 127.0.0.1 --port 8107`.
  `ALLOWED_ORIGINS` is a first-class env var the backend already reads
  (`server/backend/main.py`) to extend its CORS allow-list — **no source
  file was patched** to add port 5307; `git diff origin/main -- server/`
  is empty. `server/ingestion/seed_demo.py` was run per the repo's own
  `gui-parity.playwright.config.mjs` recipe; it no-op'd ("review_queue.json
  already present — leaving it alone"), confirming the review queue served
  during this audit is the repo's real working data, not a fixture.
- **Frontend**: `cd dashboard && npm install && VITE_API_BASE=http://127.0.0.1:8107 npm run dev -- --host 127.0.0.1 --port 5307 --strictPort`.
- **Runner**: the shared, pre-provisioned `/home/user/.a11y-runner`
  (pinned Playwright 1.62.1 + `@axe-core/playwright` 4.12.1, pinned
  Chromium). Its own `playwright.config.js`/`tests/` were not modified.
  A throwaway driver (`playwright.config.js` + `tests/audit.spec.js`) was
  written under a scratch directory with `node_modules` symlinked to the
  shared runner's install, mirroring `tests/federation-smoke.spec.js`'s
  `networkidle` + 800ms hydration-settle pattern, extended to loop over 5
  routes × 4 checks × 2 viewports plus a design-system-evidence capture.
  This driver file was deleted after the run (not left in the shared tree).
- **Routes/states scanned** (5, matching real routes in
  `dashboard/src/App.jsx` per `docs/GUI_AUDIT.md` — the primary route plus
  4 more, chosen from the task's candidate list, all of which exist in this
  app): `/` (Overview), `/map` (Map), `/assets` (Assets), `/review` (Review
  Queue), `/monitoring` (Monitoring).
- **Viewports**: `mobile-compact` 390×844 and `desktop` 1280×800 (both
  Chromium/Desktop-Chrome device profiles, viewport override only).
- **Checks per route/state**: axe-core critical/serious violations = 0;
  keyboard focus outline visible after one `Tab` press; no horizontal
  document overflow; every visible `<button>` ≥ 44px CSS px in both
  dimensions.
- **Map tile requests**: this sandbox has no internet access, and
  `AssetMap.jsx` fetches raster tiles from `a.tile.openstreetmap.org` and
  `server.arcgisonline.com` (hard-coded external URLs, not self-hosted
  despite `docs/GUI_AUDIT.md`'s "self-hosted vector/raster map" framing of
  the *overall* map feature — the basemap tiles themselves are third-party).
  These would otherwise stall Playwright's `networkidle` wait indefinitely
  (the same class of issue noted in ovnis-pr's audit). The driver's own
  `playwright.config.js`/spec (not the shared runner's) aborts requests
  matching `tile.openstreetmap.org` and `arcgisonline.com` at the route
  level before every `page.goto`. This means `/map`'s scan reflects the
  page's DOM/controls/chrome faithfully, but the raster basemap itself
  never paints (empty/gray tile layer) — see §5 scope limitations.
- **Design-system evidence**: `/assets` was used to capture one button, one
  badge, and one dialog/sheet screenshot at each viewport (`docs/a11y-evidence/assets-{button,badge,dialog}-{desktop,mobile-compact}.png`).

## 3. Results by route/state × viewport

| Route/state | Viewport | axe critical | axe serious | Keyboard focus | No h-overflow | Touch ≥44px | Notes |
|---|---|---|---|---|---|---|---|
| `/` Overview | desktop 1280×800 | 0 | 2 rules (`color-contrast`, `link-in-text-block`) | ✅ | ✅ | ❌ 4 buttons | |
| `/` Overview | mobile-compact 390×844 | 1 rule (`button-name`) | 2 rules (`color-contrast`, `link-in-text-block`) | ✅ | ✅ | ❌ 5 buttons | |
| `/map` Map | desktop 1280×800 | 0 | 1 rule (`link-in-text-block`) | ✅ | ✅ | ❌ 21 buttons | tiles aborted, basemap blank (see §2) |
| `/map` Map | mobile-compact 390×844 | 1 rule (`button-name`) | 0 | ✅ | ✅ | ❌ 22 buttons | tiles aborted, basemap blank |
| `/assets` Assets | desktop 1280×800 | 0 | 1 rule (`color-contrast`) | ✅ | ✅ | ❌ 9 buttons | |
| `/assets` Assets | mobile-compact 390×844 | 1 rule (`button-name`) | 0 | ✅ | ✅ | ❌ 10 buttons | |
| `/review` Review Queue | desktop 1280×800 | 1 rule (`button-name`, 2 nodes) | 1 rule (`color-contrast`) | ✅ | ✅ | ❌ 21 buttons | |
| `/review` Review Queue | mobile-compact 390×844 | 1 rule (`button-name`, 3 nodes) | 1 rule (`color-contrast`) | ✅ | ✅ | ❌ 22 buttons | |
| `/monitoring` Monitoring | desktop 1280×800 | 0 | 1 rule (`color-contrast`) | ✅ | ✅ | ❌ 13 buttons | |
| `/monitoring` Monitoring | mobile-compact 390×844 | 1 rule (`button-name`) | 1 rule (`color-contrast`) | ✅ | ✅ | ❌ 14 buttons | |

10/10 route×viewport combinations pass keyboard-focus-visible and
no-horizontal-overflow. 10/10 fail the touch-target-minimum check. 6/10
have at least one axe critical/serious rule violation (all of mobile, plus
Overview/Map/Assets/Review/Monitoring desktop each still failing on
`color-contrast` or `button-name`/`link-in-text-block`).

## 4. Prioritized findings

### Critical

**1. Mobile hamburger menu button has no accessible name (axe `button-name`, critical).**
`dashboard/src/components/layout/DashboardLayout.jsx` (~line 35):
```jsx
<button onClick={() => setCollapsed(c => !c)} className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200">
  <Menu className="h-5 w-5" />
</button>
```
No `aria-label`, no visible text, and the `Menu` icon isn't marked
`aria-hidden`. Confirmed live via axe on all 5 scanned routes at
390×844 (selector `.p-1\.5`); does not render at desktop width. Screen
reader users on mobile have no way to know what this control does or that
it opens navigation. **Fix**: add `aria-label="Toggle navigation"` (or
similar) to the button.

**2. `ReviewPage` severity/tier filter `<Select>` triggers have no accessible name (axe `button-name`, critical) — both viewports.**
`dashboard/src/pages/ReviewPage.jsx:167-174`:
```jsx
<Select value={sev} onValueChange={(v) => setFilter({ sev: v, offset: 0 })}>
  <SelectTrigger className="h-7 w-[110px] text-xs"><SelectValue /></SelectTrigger>
  ...
</Select>
<Select value={tier} onValueChange={(v) => setFilter({ tier: v, offset: 0 })}>
  <SelectTrigger className="h-7 w-[90px] text-xs"><SelectValue /></SelectTrigger>
  ...
</Select>
```
Selectors: `.w-\[110px\]`, `.w-\[90px\]`. Root cause, confirmed by
inspecting the live DOM and axe's own `any` checks: Radix's
`SelectTrigger` renders `<button type="button" role="combobox" ...>` and
the `<SelectValue>` text ("all") *is* present as visible `textContent`,
but per the ARIA-in-HTML accessible-name computation the `combobox` role
does not derive its name from content the way a plain `button` role does —
axe's `button-has-visible-text` check (which does account for role
overrides) reports "Element does not have inner text that is visible to
screen readers" even though a sighted user sees "all". No `aria-label` is
set to compensate. This is fixable per-instance, not a systemic
Radix/shadcn composition gap in this codebase — a source sweep
(`grep -rn "<SelectTrigger" dashboard/src`) shows every other `<Select>`
trigger already sets `aria-label` correctly: `AssetsTable.jsx` ("Filter by
asset type"/"subtype"/"status"), `AlertsPage.jsx`, `RegulatoryPage.jsx`
(3 selects), `RegulatoryReviewPage.jsx`, and `MonitoringCharts.jsx`
("Monitoring series"/"Monitoring site") all do this correctly — so
`ReviewPage` is the outlier. The same static sweep also turned up two more
instances of the identical missing-`aria-label` defect that this audit did
not live-scan (their routes/mount points were out of the 5 scanned):
`dashboard/src/pages/LiveLogsPage.jsx:62` (`/logs`'s event-type filter) and
`dashboard/src/components/OutagesPanel.jsx:67` (`/outages`'s type filter).
A third instance in `dashboard/src/components/ReviewQueue.jsx:56,60` is
moot — that component is the orphaned/unmounted one already flagged in
`docs/GUI_AUDIT.md` §4 finding 6 and is not reachable from any route.
**Fix**: add `aria-label="Filter by severity"` / `"Filter by evidence
tier"` to `ReviewPage`'s two triggers, and the equivalent to `LiveLogsPage`
and `OutagesPanel`, matching the pattern already used correctly elsewhere.

### Serious

**3. Mobile sidebar renders open-by-default and its dismiss scrim blocks the very control meant to close it (confirmed live, not axe-detected).**
`dashboard/src/contexts/SidebarContext.jsx` initializes
`collapsed = false` unconditionally. `DashboardLayout.jsx` computes
`sidebarOpen = isMobile ? !collapsed : true`, so on first paint at a
390px viewport the full sidebar is open, and the scrim
(`<div className="fixed inset-0 bg-black/50 z-30" onClick={() => setCollapsed(true)} />`)
covers the entire viewport at `z-30` — **above** the mobile header bar
(`z-20`) that contains the hamburger toggle. Confirmed live: Playwright's
own actionability check refused a direct click on the hamburger
(`button.p-1\.5`), reporting `"...<aside>...subtree intercepts pointer
events"`, twenty-plus retries, then timeout. The only way to dismiss the
overlay is to tap the narrow strip of scrim to the right of the 256px-wide
`<aside>` (in a 390px viewport, a ~134px-wide sliver) — there is no
keyboard (`Escape`) handler on the scrim either. Combined with finding #1
(the hamburger itself has no accessible name), a keyboard or screen-reader
user landing on this app at phone width has no discoverable, labeled way
to reach the page's primary content on first load. **Fix**: default
`collapsed` to `true` on mobile (e.g. seed from `useIsMobile()` in
`SidebarProvider`), and/or lower the scrim's z-index below the header, and/or
add an `Escape`-key handler to close it.

**4. Systemic `color-contrast` failures (serious) — Tailwind `slate-500`/`slate-600` text on dark backgrounds.**
Representative example, confirmed via axe's own contrast computation:
`<span class="block text-[10px] text-slate-500 font-mono uppercase tracking-wider">PR Monitor</span>`
(sidebar caption) — foreground `#64748b` on background `#0f172a`,
**contrast ratio 3.75:1**, required 4.5:1 (WCAG AA, normal text). This
single Tailwind color pairing (`text-slate-500`/`slate-600` on
`slate-900`/`slate-950`/`bg-slate-900/70` surfaces) recurs 7-20+ times per
page — stat-tile captions and sub-values, table secondary/meta text
(operator/id lines in `AssetsTable`), badge counters, review-record
metadata — and fired on Overview, Assets, Review, and Monitoring (both
viewports for Overview/Review/Monitoring; desktop-only surfaced it for
Assets since the mobile Assets scan already had a `button-name` critical
first). **Fix**: raise the muted-text token to at least `slate-400`
(`#94a3b8`, ~5.4:1 against `#0f172a`) wherever it's used for body-weight
text below 14px, or increase weight/size where the smaller ratio
(3:1 for large text) legitimately applies.

**5. `link-in-text-block` (serious) — inline links styled by color alone, insufficient contrast.**
`OverviewPage.jsx`: `<a class="text-sky-400 hover:text-sky-300" href="/assets?unmapped=1">Review them in the assets table</a>`
inside `<p class="-mt-3 text-[11px] text-slate-500">` — link color `#38bdf8`
against the paragraph's `#64748b`, contrast **2.22:1** (required 3:1), no
underline or other non-color distinguisher. Same pattern for
`<a class="text-red-300 hover:text-red-200" href="/alerts?critical=1">481 life-safety critical alert(s) open</a>`,
**2.5:1**. Both confirmed live on `/` at both viewports. Also on `/map`
(desktop only): `a[href$="maplibre.org/"]`, MapLibre's own built-in
attribution link — third-party library markup, not app code, flagged for
completeness. **Fix**: add `underline` (or equivalent) to the two
app-authored links on Overview; the MapLibre attribution link is outside
this repo's control.

**6. Touch-target-minimum failures — pervasive, both viewports, every route scanned.**
10/10 route×viewport combinations fail. This is not a mobile-only
regression — the same undersized controls render at desktop width too,
just with more surrounding whitespace. Representative offenders (class
names / labels, height×width in CSS px):
- Sidebar collapse chevron, `aria-label="Collapse sidebar"`, class `p-1`: **22×22**.
- Mobile hamburger, class `p-1.5`: **32×32** (mobile only).
- Overview's "AI Status Recap": **30**px tall; "Send Alert": **30**px tall.
- The fixed "Ask AI" launcher (bottom-right, all routes): **42**px tall — 2px short.
- Map's 7 layer-toggle chips (Power/Water/Wastewater/Other/Municipios/Events/Alerts): **26.5**px tall each.
- Map's basemap "Map"/"Satellite" buttons: **30.5**px tall.
- MapLibre's own `NavigationControl` zoom +/− buttons: **29×29** (third-party library markup).
- Review's per-row Accept/Reject buttons: **28**px tall; "Select all on page": **16**px tall; per-row select checkboxes: **16×16**.
- Monitoring's 7d/30d/90d/all range buttons: **23**px tall; the 6 incident-transition buttons (acknowledged/assigned/suppressed/resolved/reopened/threshold_migrated): **25**px tall.

**Fix**: raise the shared `Button` component's `sm` size variant (and the
bespoke inline buttons that don't use it) to a 44px minimum hit target —
padding can stay visually compact via `min-height`/`min-width` without
changing the visible chip size, which is the standard WCAG 2.5.5/5.2.5
technique.

### Not a finding

Everything else driven live — page load, data rendering (19,723 real
assets / 4,339 real alerts), tab-order focus visibility, and absence of
horizontal scroll — matched expectations at both viewports on all 5
routes with no further axe violations beyond what's listed above.

## 5. Scope limitations

- **Only 5 of 19 routed pages/states were scanned**: `/`, `/map`,
  `/assets`, `/review`, `/monitoring`. **Not covered**: `/alerts`,
  `/alerts/:id`, `/outages`, `/cave-karst`, `/regulatory`,
  `/regulatory/review`, `/environmental-exposure`, `/analytics`, `/logs`,
  `/system`, `/water-disruption` (already confirmed broken under
  split-port `npm run dev` per `docs/GUI_AUDIT.md` §4.2 — its iframe would
  not have rendered the intended console in this same dev setup),
  `/sector/:sector`, `/events/:id`, `/municipios/:name` — chosen per the
  task's candidate-route list, all of which are real, live routes in this
  app; the remaining 14 were out of scope for this pass.
- **In-page states not separately scanned**: the `AssetDetail` sheet/dialog
  (screenshotted for design-system evidence but not independently
  axe-scanned in its open state), the "Ask AI" floating panel in its open
  state, any URL-filtered state (e.g. `?critical=1`, `?unmapped=1`), and
  the System page's API-key form (gated behind `API_SECRET_KEY`, unset in
  this sandbox — matches Phase 1's finding).
- **Only one theme was possible to test**: the app ships dark-only CSS
  with no light palette and no toggle (see
  `docs/design-system-usage.json`), so "light theme not covered" is not a
  gap in this audit's execution — there is no second theme to reach.
- **`/map`'s basemap tiles never painted.** This sandbox has no internet
  access; `AssetMap.jsx` fetches raster tiles from
  `a.tile.openstreetmap.org` and `server.arcgisonline.com`, which were
  aborted at the route level to keep Playwright's `networkidle` wait from
  stalling indefinitely (see §2). The map's DOM/controls/layer-toggle
  chrome was still fully rendered and scanned, but the actual raster
  basemap paint, any tile-dependent visual contrast, and canvas-rendered
  marker/cluster click interactions (already noted as unreachable in
  headless Chromium per `docs/GUI_AUDIT.md` §2.2) were not exercised.
- **Backend auth, notification, and AI-query integrations were not
  exercised** in this pass (Phase 1 already covered their graceful-503/
  no-channels-configured behavior; this audit is accessibility-focused,
  not functional).
- **Single browser engine**: Chromium 1194 (pinned) only — no Firefox or
  WebKit/Safari pass, and no real assistive-technology pass (NVDA,
  JAWS, VoiceOver) — the keyboard-focus-visible check is a CSS
  `outline-style` proxy, not a screen-reader transcript.
- **No 200%-zoom/reflow test, no reduced-motion test, no automated
  color-contrast check beyond what axe-core computes** (the federation
  package's own `test-harness.contract.json` advertises a
  `reducedMotion` check; this audit did not run it against the app).
- **Desktop-launcher (same-origin) packaging path not exercised** — only
  the split dev-server ports (8107 backend / 5307 frontend) were tested,
  per the task's port assignment; `desktop/app_server.py`'s same-origin
  `prii_desktop` wrapper was not booted.
