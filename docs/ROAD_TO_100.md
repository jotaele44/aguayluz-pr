# Road to 100% — aguayluz-pr

Provenance-honest completion ledger for the `aguayluz-pr` federation node
(water / power / utility infrastructure intelligence producer for the Puerto Rico
control plane). It records what is **done**, what remains, and — for each remaining
item — whether closing it is a **code** task (actionable inside this repo) or a
**data / live-feed** task (blocked on an external source, not on missing modules).

**Current completion: ~90%.** This is the most complete producer in the federation.
The remaining ~10% is **data-provenance / live-feed hardening (T2 → T1)**, not absent
functionality. Every ingest adapter, validation gate, export path, dashboard, and
desktop shell already exists and is tested; what is missing is *live, continuously
attributed* electric-outage data, which is gated by a third-party WAF and by the
absence of a permissioned utility feed — external facts this repo cannot manufacture.

Status is self-declared in `federation.json` as `PRODUCTION_REAL_DATA_PARTIAL`.
This ledger does **not** claim any live outage figure it cannot reproduce offline.

---

## Leverage-ordered checklist

Ordered by impact-per-unit-effort. The highest-leverage remaining items are all
**data/live-feed** bound — they raise the *tier* of an existing, working pipeline
rather than adding new code.

| # | Item | Kind | Status | Leverage |
|---|------|------|--------|----------|
| 1 | `fetch_luma_live.py` typed source-unavailable handling | code | **DONE (this PR)** | high — small, unblocks clean orchestration |
| 2 | Live per-municipio electric-outage feed (MiLUMA/PREB) → T1 | data/live-feed | **BLOCKED** (WAF 403 / no permissioned feed) | highest — promotes the whole `aee_incidents` stream T2→T1 |
| 3 | Per-municipality outage **start/end + restoration diffing** | data + code | **FUTURE EXTENSION** (needs a live time series first) | high — turns snapshots into true incident lifecycles |
| 4 | Refresh `aee_incidents` beyond the 2025-03-03 snapshot | data | **BLOCKED** (recommended mirror inactive) | medium — depends on #2 |
| 5 | In-repo hosting of the external source datasets | data/ops | **DEFERRED** (by design; `--src` overrides) | low — convenience, not correctness |

---

## Done

Core package and pipelines are real, committed, and tested.

- **Core `src/aguayluz/` package** — EPA WATERS REST client (NHDPlus V2.1, PR = VPU 21),
  alert engine, confidence/tier model, and the `aguayluz` Typer CLI.
- **15+ real ingest pipelines** (`scripts/ingest_*.py`, 12 `ingest_*` + builders/fetchers):
  POWER assets, WATER/wastewater assets, NWS active alerts, USGS water sites + daily
  levels, USGS PR-region earthquakes (keyless FDSN feed), EPA SDWIS violations,
  EPA ECHO CWA enforcement, FEMA disaster declarations, PREPS emergency-portal events,
  AEE/LUMA per-municipio outages, news-event signals.
- **8 federation validation gates** (`src/aguayluz/validation.py`, run via
  `scripts/validate_repo.py`):
  - G01 — schema validation of every exported entity
  - G02 — every output backed by a `source_manifest` entry
  - G03 — every entity carries confidence + tier
  - G04 — review-queue presence + shape
  - G05 — coverage ledger
  - G06 — Base44 export sanitization
  - G07 — no secrets in tracked files
  - G08 — tests-pass marker
- **Full React/Vite dashboard** (`dashboard/`) with geo map layers.
- **Desktop app** shell (`desktop/`, `PRII-AGUAYLUZ.*` launchers, Gatekeeper helper).
- **180+ tests** (`tests/`), comprehensive CI (`.github/workflows/`).
- **Real committed corpus**: 273 utility assets (39 POWER generation/substation/
  transmission + 234 WATER/wastewater nodes), PREPS/AEE service events, and geo
  layers (78 municipio polygons, 901 barrios, Census-Gazetteer centroids).

---

## Water-monitoring analytic layer (closed here)

The water-monitoring vectors that were *declared but unbuilt* — active alert
modules with a seed-only `alert_events.jsonl`, a blocking dependency gap, and an
unwired NHDPlus enricher — are now real, tested code:

| Vector | What landed | Tier | T1 unblock (external) |
|---|---|---|---|
| SDWIS → CONTAMINATION alerts | `scripts/build_water_alerts.py` promotes 725 boil-water + 2,515 health-based quality violations to `AlertEvent`s | **T1** (real EPA data) | — already T1 |
| Reservoir low / drought → HYDRO_OPS | per-site percentile proxy over `reservoir_levels.jsonl` | **T2 / needs_review** | official AAA operating levels (niveles de control) |
| Water↔power crosswalk (GAP-003) | `scripts/build_water_power_crosswalk.py` — 87 `energizes` edges by nearest-power proximity; GAP-003 → closed | proxy (`evidence_required`) | real utility feeder map |
| NHDPlus enrichment | `scripts/enrich_waters_nhd.py` wires the existing WATERS client; exporter emits `comid/reachcode/vpuid` | T1 when run | api.data.gov WATERS key + network |
| Rich export → Hub | `federation_export.py` carries asset `attributes` + `energized_by` relationships for the Hub water surface | — | — |

Only fully-sourced vectors (SDWIS) claim T1; proxies are transparently tagged and
carry their unblock condition. `owld_locator` downstream-contamination cascade is a
noted follow-up (client implemented, not yet wired to alert generation).

## Remaining — code (closed here)

Exactly one small, clearly-safe robustness fix, applied in an earlier PR:

- **`scripts/fetch_luma_live.py` — typed source-unavailable result on WAF/403.**
  Previously `fetch_towns` let `urllib.error.HTTPError` (the expected Incapsula WAF
  403) and `URLError` (network failures) propagate as an **uncaught traceback** — a
  crash, not a signal. The fetch now raises a typed `SourceUnavailable`, and `main`
  turns it into a one-line `source-unavailable: …` message on stderr plus a dedicated
  exit code (`EXIT_SOURCE_UNAVAILABLE = 2`), so `refresh.py --all` (which already
  treats this step as optional) warns-and-continues cleanly instead of surfacing a
  stack trace. Covered by offline unit tests (`tests/test_fetch_luma_live.py`) that
  mock `urlopen` to raise 403 / 500 / `URLError` — **no real network**.

  The validation gates and ingest data were intentionally **not** touched.

No other code work is required to reach 100% functional completeness. The remaining
gap is entirely data/live-feed provenance, below.

---

## Remaining — data / network-blocked (not missing modules)

These cannot be closed from inside this repo. They are external-source facts; the
adapters that would consume them already exist and are source-agnostic (`--src`).

1. **`aee_incidents` is a point-in-time snapshot (2025-03-03).**
   The data was captured from the `SuperSonicHub1/luma-energy-outages` mirror, which
   is **itself inactive since that date** and carries no per-record timestamps. The
   committed payload is a reproducible snapshot stamped **T2 / `needs_review`**.

2. **No live per-municipio outage feed.**
   `api.miluma.lumapr.com` sits behind an Incapsula WAF that returns **HTTP 403** to
   plain clients (added ~2025-03, which killed the mirror). `fetch_luma_live.py` makes
   a best-effort browser-header attempt but **success is not guaranteed** and is now
   handled as a typed source-unavailable outcome (item above). LUMA has asked third
   parties to stop republishing. The recommended path to **T1** is a formal
   PR Energy Bureau (PREB) / LUMA data-sharing arrangement, not a scraper.

3. **Several source datasets live outside the repo.**
   `Energy_Sector/…`, `preps_*.json`, `outages_by_town.json`, and the Census gazetteer
   are referenced by default local paths; ingest scripts override with `--src`. This
   is deliberate (keeps the repo light); it is an ops/convenience item, not a defect.

4. **Status is self-declared.** `production_status` in `federation.json` is
   `PRODUCTION_REAL_DATA_PARTIAL`; `federation_readiness_gate` documents the T2/live
   caveats as advisories rather than blockers.

**Bottom line:** the remaining ~10% is **live-feed hardening (T2 → T1)** — promoting an
existing, working pipeline from third-party snapshot to continuously attributed live
data — not the construction of any missing module.

---

## Named future extension — per-municipality outage lifecycle

Once a **live** per-municipio source (item 2 above) is wired, the natural next step is
to reconstruct true outage **lifecycles** rather than snapshots:

- **Per-municipality outage start / end + restoration diffing.**
  Walk successive live snapshots (or the commit history of `data/aee_incidents.jsonl`),
  **diff** consecutive states per municipio/zone, and emit derived events:
  `outage_start`, `outage_ongoing`, and `restoration` (outage cleared), with real
  `start_time` / `end_time` and restoration durations. This turns the current
  point-in-time `outage` events into continuous incident records suitable for T1
  attribution and SLA/restoration analytics.

This extension is **blocked on the live feed**, not on adapter code: `ingest_aee.py`
is already source-agnostic and the event schema already carries the time fields the
diff would populate.

---

## Live-run log

Real materializations of the corpus from the keyless public federal APIs. Each row
is what the producer **actually fetched** on the stated date (no fabricated data);
counts are post-merge file totals where noted.

### 2026-07-18 — new vector: USGS PR-region earthquakes

Added `scripts/ingest_usgs_quakes.py` (keyless USGS FDSN event service) and ran it
live via the proxy against the PR bounding box (lat 17.5–19.0, lon -68.0 to -65.0)
at the default M≥2.5 / 30-day window. This is the feed that backs the now-active
`SEISMIC_GEO` alert module.

| Source | Host | Result | Rows |
|--------|------|--------|------|
| USGS earthquakes → `service_events` | `earthquake.usgs.gov` | OK | 80 PR-region events (M≥2.5, trailing 30 days); file total **24923** |

The step is idempotent (merges by `USGS-EQ` `source_ref` prefix) and now runs first
in both `--daily` and `--weekly` alongside NWS. Committed rows are a trailing-window
snapshot; a later refresh replaces the whole `USGS-EQ` slice. Offline unit tests
(`tests/test_ingest_usgs_quakes.py`, fixture `tests/fixtures/usgs_pr_quakes_sample.json`)
cover bbox/magnitude filtering, schema conformance, and merge idempotency — no network.

### 2026-07-12 — keyless weekly refresh

Run with `scripts/refresh.py --weekly` (venv, live network via proxy), which
executes in order: **NWS → USGS sites → USGS levels → SDWIS → ECHO (best-effort) →
FEMA (best-effort) → federation export**. ECHO and FEMA are marked **optional**
(warn-and-continue, like the WAF-gated MiLUMA step), so the chain completes through
the export even while those two endpoints 404. `fetch_luma_live.py` is not part of
`--weekly` and was skipped (Incapsula WAF 403, expected). The full run exits 0 and
reaches the export step.

| Source | Host | Result | Rows |
|--------|------|--------|------|
| NWS active alerts | `api.weather.gov` | OK | 0 active PR alerts (no change; 6 events in file) |
| USGS site network → `utility_assets` | `waterservices.usgs.gov` | OK | +1267 fetched (lake 22, stream_gage 1085, irrigation_canal 61, reservoir 99); file total **8340** |
| USGS daily levels → `reservoir_levels` (gitignored) | `waterservices.usgs.gov` | OK | 3557 readings across 132 assets (streamflow 1363, gage_height 1486, reservoir_elevation 708) |
| EPA SDWIS violations → `service_events` | `data.epa.gov` (Envirofacts) | OK | 38799 violations fetched (4519 health-based, 2209 need-review); file total **24841** events |
| EPA ECHO CWA enforcement | `echo.epa.gov` | **best-effort — upstream 404** | endpoint `cwa_rest_services.get_facilities` returns HTTP 404 from the server; step is optional, no rows written, run continues |
| FEMA disaster declarations | `www.fema.gov` | **best-effort — upstream 404** | `open/v2/disasterDeclarationsSummaries` returns HTTP 404 (Drupal "Page not found"); step is optional, no rows written, run continues |
| Federation export | (local) | OK | manifest: 33286 entities / 40964 relationships / 26134 sources / 10 alerts |

Tracked-data files updated this run: `data/utility_assets.jsonl` (7088→8340),
`data/service_events.jsonl` (6→24841). ECHO and FEMA are genuine upstream endpoint
breakages (both hosts reachable, both specific REST paths 404) — not proxy blocks and
not manufacturable; their adapters remain source-agnostic (`--src`) and untouched, and
their steps are now best-effort so a `--weekly` run reproduces this materialization
(USGS/SDWIS land, then export runs) rather than aborting at the first 404.
Gates G01–G08 PASS; `ruff check` clean; `pytest -q -m "not live"` = **210 passed**
with `fastapi`+`httpx` present (includes the new backend `/events` bounding tests);
on the lightweight offline deps without `fastapi`, those backend tests skip → 197 passed.

---

## Verification (offline)

```
# Core suite (offline subset; excludes live-marked tests needing EPA_WATERS_API_KEY)
python3 -m pytest tests/ -q -m "not live"

# The one changed script's tests (mock the WAF/403 failure — no network)
python3 -m pytest tests/test_fetch_luma_live.py -q
```

Six federation/maintenance test modules import the sibling `prii_export_utils` /
`prii_maintenance` packages (hosted in `thehub-pr`); run them in an environment where
those packages are installed. The remaining suite — including the new
`fetch_luma_live` error-handling tests — passes offline with only the lightweight
PyPI dependencies (`httpx`, `pydantic`, `jsonschema`, `pyyaml`, `typer`, `pytest`).
