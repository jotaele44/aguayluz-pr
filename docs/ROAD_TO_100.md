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
- **15+ real ingest pipelines** (`scripts/ingest_*.py`, 11 `ingest_*` + builders/fetchers):
  POWER assets, WATER/wastewater assets, NWS active alerts, USGS water sites + daily
  levels, EPA SDWIS violations, EPA ECHO CWA enforcement, FEMA disaster declarations,
  PREPS emergency-portal events, AEE/LUMA per-municipio outages, news-event signals.
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

## Remaining — code (closed here)

Exactly one small, clearly-safe robustness fix, applied in this PR:

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
