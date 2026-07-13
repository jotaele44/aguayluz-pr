# Dashboard UI Cleanup & Optimization Plan

> Scope: the diagnostic dashboard under `dashboard/` (React 18 + Vite 6 +
> Tailwind + shadcn/ui + react-query + MapLibre GL). This is the
> **diagnostic-only** producer surface per ADR 0001 — the plan optimizes it as
> a developer/operator tool, not as an end-user product. No backend or
> federation-contract changes are proposed.

This is a **plan**, not a code change. It inventories the current app design and
interactive workflow, flags concrete defects and redundancy (with `file:line`
anchors), and sequences the work into reviewable phases. Each item lists intent,
effort (S ≤1h · M ≤half day · L ≥1 day), and risk.

---

## 1. Current state (as built)

**Shell.** `App.jsx` mounts a single `DashboardLayout` (fixed `Sidebar` +
`StatsBar` + `<Outlet/>`) over 10 routed pages. Router switches between
`BrowserRouter` and `HashRouter` on `VITE_OFFLINE` for the single-file export.

**Routed pages (10):** Overview `/`, Map `/map`, Assets `/assets`, Outages
`/outages`, Monitoring `/monitoring`, Review `/review`, Analytics `/analytics`,
Live Logs `/logs`, Sector detail `/sector/:sector`, Repo Analyzer
`/tools/repo-analyzer`.

**Data layer.** `lib/api.js` → `lib/hooks.js` (react-query) over a stdlib
FastAPI read backend; `api.js` swallows all fetch errors into fallbacks, and an
`OFFLINE` path resolves from a baked `snapshot.json`.

**Design language.** Hand-rolled dark "slate" palette applied as literal
Tailwind classes (`bg-slate-950/900/800`, `text-slate-*`) across every
component, plus per-file accent colors for sectors/event-types/severity.

The app is functional and visually coherent. The problems are **redundancy,
dead code, a split design system, a few real bugs, and workflow friction** — not
a broken UI.

---

## 2. Defects to fix first (correctness)

> **Resolved design decisions (drive several items below):** (1) **drop** the
> neon theme entirely — retune the semantic tokens to the slate palette the app
> actually renders; (2) **remove** the Repo Analyzer page outright. Items D4/D5,
> §3, §4.1, §7, and §9 reflect these.

| # | Issue | Location | Fix | Effort |
|---|-------|----------|-----|--------|
| D1 | **Rules-of-Hooks violation.** `useMemo` for `groups` is declared *after* an early `return` (the `isLoading` guard), so the hook count changes between renders. Works today only because loading→loaded remounts, but it is a latent crash. | `components/OutagesPanel.jsx:52` (after the `return` at `:42-50`) | Move the `groups` `useMemo` above the loading guard. | S |
| D2 | **Dead Leaflet override** for a MapLibre app. `.leaflet-container` rule has no effect; the real map background lives in `AssetMap`'s `OSM_STYLE`. | `index.css:95-98` | Delete the rule. | S |
| D3 | **Tailwind references undefined tokens.** `tailwind.config.js` maps `chart-1..5` and `sidebar-*` colors to CSS vars that `index.css` never defines, so any `bg-chart-1`/`bg-sidebar` resolves to an invalid color. | `tailwind.config.js` colors vs `index.css:8-40` | Either define the tokens or drop the unused color keys. | S |
| D4 | **External font `@import` breaks offline builds.** `index.css:1` render-blocks on Google Fonts over the network — a `file://` offline export cannot reach it, so the export silently falls back to system fonts. | `index.css:1` | Self-host the two families (or use a system stack) so online and offline render identically. | M |
| D5 | **Unauthenticated GitHub calls from the browser.** Repo Analyzer hits `api.github.com` directly (60 req/hr shared IP limit, no token); it fails opaquely under load and is out of scope for a water/power diagnostic. | `pages/RepoAnalyzerPage.jsx:23-30` | **Remove** the Repo Analyzer (see §7) — retires this by deletion. | S |

---

## 3. Dead & orphaned code (safe deletions)

Removing these shrinks the surface with zero behavior change.

- **`pages/Dashboard.jsx` (151 lines) — orphaned.** Not imported by `App.jsx`;
  it is the pre-split single-screen version superseded by `OverviewPage` +
  `MapPage`. Carries its own `HeaderMetric`/`TabLabel` helpers. **Delete.**
- **Dead helpers in `lib/format.js`:** `bandMeta`, `bandHex`, `statusMeta`
  (`:6-38`) are never imported anywhere — leftovers from the "anomaly band"
  seed template this dashboard was scaffolded from. **Delete** (keep
  `tierBadge`, `fmtDate`, which are used).
- **Unused `index.css` cosmetics:** `.glow-cyan`, `.glow-border`,
  `.panel-glass`, `.stream-cursor`, and the `--glow-*`/`--panel-bg`/`--grid-color`
  tokens are not referenced by any component. **Delete** — part of the neon-theme
  removal decision (§4.1).
- **`pages/RepoAnalyzerPage.jsx` (150 lines) — remove per decision.** Delete the
  file, its route (`App.jsx:15,37`), and the sidebar nav entry + now-unused
  `GitBranch` import (`Sidebar.jsx:2-4,19`). Retires D5.
- **Unused shadcn/ui primitives:** ~45 files in `components/ui/`, of which only
  ~12 are imported (`badge, button, input, select, skeleton, sheet, tabs,
  table, toast/toaster, use-toast`). The rest (carousel, calendar, menubar,
  navigation-menu, resizable, input-otp, drawer, chart, sidebar, etc.) and their
  Radix deps in `package.json` are dead weight. **Prune** the unused files and
  the corresponding `@radix-ui/*`, `embla-carousel-react`, `cmdk`, `vaul`,
  `input-otp`, `react-day-picker`, `react-hook-form`, `next-themes`,
  `react-markdown`, `react-resizable-panels` dependencies after confirming no
  imports. Verify with the existing `eslint-plugin-unused-imports`.

_Effort: S each; do as one "remove dead code" commit, gated by `npm run build`._

---

## 4. Design-system consolidation (the core cleanup)

The app currently runs **two parallel color systems**: (a) the semantic
CSS-variable theme in `index.css`/`tailwind.config.js` (cyan-neon `--primary`,
grid background) that is **almost never used**, and (b) literal `slate-*`
Tailwind classes that are **what actually renders**. They don't match, and every
component re-derives its own accent maps.

**Goal:** one source of truth for color and one for chart styling.

1. **Drop the neon theme (decided).** Keep the rendered slate/`sky-400` look and
   *remove* the cyan-neon layer wholesale:
   - Delete the dotted-grid `body` background (`index.css:48-54`) and the
     `--glow-*`/`--panel-bg`/`--grid-color` tokens + `.glow-*`/`.panel-glass`/
     `.stream-cursor` rules (also §3).
   - Retune the semantic tokens (`--primary`, `--accent`, `--ring` at
     `index.css:15,21,27`, currently `187 100% 50%` cyan) to the slate/sky
     values the app already renders, and set `--background/card/border` to those
     same slate values so `bg-background`/`border-border` finally agree with the
     literal `slate-*` classes.
   - Replace the Google-Fonts `@import` (`index.css:1`) with a system font stack
     (or self-host) — this also fixes D4 (offline export).
2. **Centralize accent maps** into `lib/aguayluz-format.js` (already the home for
   `typeMeta`/`statusBadge`/`severityTone`). Today the same maps are copied:
   - **Event-type → color** duplicated 3× with drifting shades:
     `LiveLogsPage.jsx:12-18` (`TYPE_TONE`), `OutagesPanel.jsx:13-19`,
     `AssetDetail.jsx:14-20`. → one `eventTypeMeta(type)`.
   - **`EVENT_TYPES`** array duplicated: `LiveLogsPage.jsx:19` &
     `OutagesPanel.jsx:21`.
   - **`SEVERITIES`/`TIERS`** duplicated: `ReviewPage.jsx:15-16` &
     `ReviewQueue.jsx:15-16`.
   - **Sector metadata** duplicated with different shapes: `OverviewPage.jsx:12-17`
     (icon/color/border/bg) vs `SectorDetailPage.jsx:13-18` (icon/color/types).
     → one `SECTORS` registry.
3. **Centralize chart styling.** The Recharts tooltip/axis style object is
   re-declared four times with *different* hex values —
   `OverviewPage.jsx:19-25` (`TOOLTIP_STYLE`), `AnalyticsPage.jsx:9`
   (`TIP`), `SectorDetailPage.jsx:11` (`TIP`), `MonitoringCharts.jsx:12-13`
   (`tip`/`axis`). Plus a standalone `COLORS` palette at `AnalyticsPage.jsx:10`.
   → export `chartTheme` (tooltip, axis, grid stroke, categorical palette) from
   `lib/format.js` and import everywhere. Guarantees charts match and makes the
   §4.1 palette decision propagate for free.
4. **One stat-card component.** The KPI/stat tile is reimplemented four times:
   `StatsBar.jsx:5` (`Kpi`), `OverviewPage.jsx:147` (`Kpi`),
   `Dashboard.jsx:23` (`HeaderMetric`, dies with §3), `RepoAnalyzerPage.jsx:143`
   (`Stat`). → one `<StatCard>` in `components/ui/` (or `components/`), with
   `emphasis`/`tone` props covering the variants.

_Effort: L overall, but each of 4.2–4.4 is an independent M-sized commit._

---

## 5. Redundancy in the workflow itself

- **KPIs shown twice on Overview.** The global `StatsBar` (Assets, Mapped,
  Events, Readings, Coverage, Review) is always visible, yet `OverviewPage`
  opens with its own KPI row repeating Assets / Coverage / Pending Review
  (`OverviewPage.jsx:75-80`). Backend-status dot is also shown in **both**
  `Sidebar.jsx:68-76` and `StatsBar.jsx:53-59`. → Make `StatsBar` the single
  KPI/status source; replace the Overview KPI row with content that isn't
  already in the bar (e.g. trend deltas, last-refresh time), and drop the
  sidebar dot (or keep only the sidebar one and slim the bar).
- **Two review surfaces.** `ReviewPage` (paginated, with accept/reject/skip) and
  the `ReviewQueue` component embedded in the Map tab, which is read-only and
  literally tells the user to "use the Review page for actions"
  (`ReviewQueue.jsx:53-55`). The filter/sort logic is duplicated. → Extract one
  `useReviewFilters` hook + a shared row renderer; let the Map-tab instance opt
  into actions instead of maintaining a second read-only copy.
- **Map-tab overlap with standalone pages.** The Map right rail re-embeds
  `AssetsTable`, `OutagesPanel`, `MonitoringCharts`, `ReviewQueue`
  (`MapPage.jsx:40-53`) — the same components the Assets/Outages/Monitoring/Review
  pages render full-screen. That's intentional (map + context), but confirm it's
  the desired IA rather than accidental duplication; consider deep-linking the
  rail tabs so `/map?panel=outages` is shareable.

---

## 6. Interactive-workflow optimization

Highest operator-value items, roughly in priority order:

1. **Keyboard triage for Review (S–M, high value).** Adjudicating 300+ records
   one mouse-click at a time is the app's heaviest interaction. Add
   `A`/`R`/`S` (accept/reject/skip) + `J`/`K` navigation and an
   optimistic-remove so the list advances without a refetch round-trip.
   `useDecision` (`hooks.js:23`) currently only `invalidateQueries` on success —
   add an optimistic `onMutate`/rollback.
2. **URL-persisted filters (M).** All filters live in component `useState`
   (`AssetsTable` type/status/review/search, `ReviewPage` sev/tier/offset,
   `LiveLogsPage` type/q). A refresh or shared link loses them. → sync to
   `useSearchParams`. Enables bookmarkable diagnostic views — valuable for a
   dev/ops tool.
3. **Virtualize long lists (M).** `AssetsTable` renders every filtered row
   (`AssetsTable.jsx:139`); README notes the asset corpus "grows beyond" the
   current 408. Add `@tanstack/react-virtual` (or windowing) to the assets table
   and the events/review lists before it becomes sluggish.
4. **Distinguish "empty" from "backend down" (S).** `api.js` collapses errors to
   empty fallbacks, so most pages render "No data" identically whether the
   source is empty or the API is unreachable. Surface the query `isError` state
   per-panel (the down banner in `StatsBar.jsx:43-51` is the only current
   signal). Consider not swallowing errors in `api.js` and letting react-query
   own retry/error state.
5. **Consistent loading/empty/error states (S–M).** Skeletons exist on some
   pages (Overview, Assets, Review) but not others (Analytics has them; Map rail
   panels vary). Standardize a `<PanelState loading|empty|error>` wrapper so
   every data panel behaves the same.
6. **A11y pass (M).** Icon-only buttons lack labels (Review skip button
   `ReviewPage.jsx:84`, filter-clear `AssetsTable.jsx:99`, sidebar collapse
   `Sidebar.jsx:40`); status is color-only in places; clickable table rows
   (`AssetsTable.jsx:140`) and sector `<Link>` cards need focus-visible and
   keyboard activation. Add `aria-label`s, `focus-visible` rings, and text/icon
   redundancy for status.

---

## 7. Performance & build

- **Remove Repo Analyzer (S, decided).** Delete `pages/RepoAnalyzerPage.jsx`,
  its `App.jsx` import + `/tools/repo-analyzer` route, and the `Sidebar.jsx` nav
  entry (drop the `GitBranch` import). Removes the out-of-scope browser→GitHub
  dependency (D5) and one route from the bundle. Do this in Phase 1 with the
  other deletions.
- **Route-level code splitting (S).** The remaining 9 pages + MapLibre + Recharts
  load in the initial bundle via static imports in `App.jsx`. `React.lazy` +
  `Suspense` per route pulls MapLibre (`~200KB+`) and Recharts off the critical
  path for users who land on Overview.
- **Dependency prune (S).** Follows §3 — dropping unused Radix/UI deps shrinks
  `node_modules` and the offline single-file export.
- **react-query cache tuning (S).** `useHealth` polls every 15s
  (`hooks.js:9`); other queries use library defaults. Set sensible
  `staleTime`/`gcTime` in `query-client.js` so tab-switching between the Map
  rail and full pages doesn't refetch identical asset/event data.
- **Memoize map inputs (S).** Confirm `AssetMap` isn't re-diffing GeoJSON on
  every parent render (selection state changes in `MapPage`/`Dashboard` can
  cascade); pass stable references.

---

## 8. Naming note

The task references "skywatcher-pr"; this repository is **`aguayluz-pr`**. The
neon theme, `.leaflet-container` override, and `bandMeta` anomaly helpers are
fingerprints of a shared upstream "skywatcher"-style dashboard template that
`aguayluz` was scaffolded from. Several items above (D2, §3 dead helpers, the
generic Repo Analyzer, and the §4.1 neon theme) are precisely the un-adapted
remnants of that template. Cleaning them — the two decided removals foremost —
is also a de-branding pass.

---

## 9. Sequenced phases

**Phase 0 — Design decisions.** ✅ Resolved: (a) **drop** the neon theme +
grid background (§4.1); (b) **remove** the Repo Analyzer (§2/D5, §7). No
review pending — folded into Phases 1–2 below.

**Phase 1 — Correctness & dead code (low risk, high signal).** §2 defects
D1–D3 + §3 deletions, **including deleting the Repo Analyzer** (page, route,
nav entry). One "fix + prune" PR, gated by `npm run build` and `npm run lint`.
No visual change intended (the analyzer was a standalone tool page).

**Phase 2 — Design-system consolidation.** §4.2 (accent maps) → §4.3 (chart
theme) → §4.4 (StatCard), each its own commit. Then §4.1 — **drop the neon
theme**: retune the semantic tokens to slate, remove the grid/glow CSS, and
swap the Google-Fonts `@import` for a system stack (also closes D4).

**Phase 3 — Workflow redundancy.** §5 (dedupe KPIs/status, unify review
surfaces) and §6.4/6.5 (state consistency).

**Phase 4 — Interaction & performance.** §6.1–6.3, §6.6 (a11y), and the §7
perf items (code splitting, cache tuning, map memoization). The Repo Analyzer
removal already landed in Phase 1.

Phases 1–2 are pure cleanup and shippable immediately; 3–4 are the optimization
payload and can land incrementally.

---

## 10. Verification per phase

- `cd dashboard && npm run lint && npm run build` green after every commit.
- `npm run build:export` (offline single-file) still renders — the offline path
  is easy to regress (fonts D4, `snapshot.json`, `document.baseURI` map URL).
- Manual smoke: Overview → Map (select asset, open detail) → Assets (filter,
  sort) → Review (accept/reject/skip a record) → Live Logs (SSE connects) with
  the FastAPI backend running per `dashboard/README.md`.
- No change to `federation.json`, `server/backend`, or the export contract.
