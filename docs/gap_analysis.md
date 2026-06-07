# Gap analysis

Refreshed for the M1→M23 build. Sorts every artifact in the repo into
**Complete** (fully wired, tested, exercised), **Partial** (wired and
tested but not yet exercised in a production path), **Stub** (shape is
right, logic is heuristic or incomplete), **Missing** (declared in the
spec but not implemented), and **Dead** (exists, but no path reaches it).

Counts at the bottom are maintained by `scripts/gap_audit.py`; CI fails on
PRs that change them without regenerating the doc (`tests/test_gap_audit.py`).

## Complete

Fully wired, has tests, exercised end-to-end in the demo chain
(`README.md` quickstart).

- **All 13 schemas** validate at G01 (`src/aguayluz/validation.py` →
  `_ENTITY_SCHEMAS`). The `additionalProperties: false` rule mechanically
  catches drift. `hub_packet.json` (M19) is the latest addition.
- **WATERS layer** — `client.py` with 429 retry, env-var fallback, header/
  query auth modes (19 mocked tests). `mapping.py` with VPU 21 partial-
  coverage rule. `navigation.py` with the WATERS-primary trace path.
- **Ingest layer** — FRS adapter + live client, FEMA adapter + live client,
  HIFLD adapter + live-with-fallback client. The generic `pipeline.py`
  serves all three.
- **Analysis layer** — dependency graph (6 edge kinds), reconciliation
  (4 finding kinds), watershed delineation (per-asset upstream area).
- **Federation handoff** — 5 per-receiver projections; G01 catches
  `handoff_*.json` files by prefix-match.
- **Hub packet** (M19) — `outputs/hub_packet.json` bundles envelope +
  handoffs + entities + deterministic SHA-256 signature; receivers can
  cache by signature and detect tamper via
  `aguayluz.hub_packet.verify_packet_signature()`.
- **History + diff** — snapshot/diff between runs; surfaces deltas as
  `RunDiff`.
- **Full-chain runner** (M18) — `scripts/run_full_chain.py` orchestrates
  M5→M15 in one command; demo mode is a regression check, `--live` hits
  the real EPA APIs, `--baseline-write`/`--baseline-check` compare against
  the committed corpus.
- **Contradictions preservation** (M18 bug fix) — `load_contradictions_
  from_report` keeps M8 findings on the envelope across M13/M15 rebuilds.
- **Live data resilience** (M22) — FRS client repairs malformed JSON
  escapes (PONCE `\S`, CAGUAS `\B`, MAYAGUEZ literal TAB), tolerates
  per-city failures without sinking the baseline, normalizes
  `SAN_JUAN` → `SAN JUAN` at the edge.
- **Live-corpus baseline** (M22) — `tests/baseline/live_corpus_summary.json`
  committed from a real 5-city / 50-FEMA-record run: 29 assets, 50
  events, 50 contradictions, all 8 gates PASS.
- **Automated drift detection** (M23):
  - Daily live-corpus cron (`live-corpus.yml` 12:00 UTC) + Slack notifier
  - Daily WATERS OAS shape monitor (`oas-monitor.yml` 13:00 UTC) with
    21 paths × method × response-ref signature pinned at
    `tests/baseline/waters_oas_shape.json`
  - Daily FRS classifier audit (same workflow) with reference at
    `tests/baseline/classifier_rate.json` (live: BAYAMON 8/648 = 1.23%)
  - `docs/upstream-changes.md` runbook for the operator-driven
    acceptance path
- **8 federation gates** (G01–G08) PASS on the demo chain.
- **CLI** — `aguayluz` Typer entry point with 15 subcommands.
- **332 tests pass** with 4 live-mode skips (no API keys in CI).
- **CI workflow** — ruff + pytest + validate_repo on every push;
  scheduled live-corpus + oas-monitor crons for drift detection.
- **Architecture docs** with drift guard (`tests/test_docs.py`).

## Partial

Wired and tested, but not exercised in the default demo chain. These are
ready to use; they just don't fire automatically.

- **WATERS endpoints wrapped but no script calls them**:
  - `event_indexing` (POST + GeoJSON batch) — useful for batch service
    events but no vector emits it yet.
  - `gnis_name_lookup` — name resolution available but ingest adapters
    don't use it (they trust the source name).
  - `owld_locator` — `mapping.service_event_from_owld()` exists as a helper
    but no script invokes it.
- **Live WATERS navigation** (`build-graph --use-waters`): wired in M12 with
  `--max-traces` cap, but the default demo chain runs heuristic-only.
  `tests/test_navigation_live.py` exercises it manually only.
- **Live FRS / FEMA / HIFLD pulls**: scripts accept `--live`, tests are
  network-gated (`EPA_LIVE_TESTS=1`). Default demo runs use fixtures.
- **`pynhd` enrichment** in `navigation.py`: NLDI PR-coverage probe is
  implemented, but no analyzer currently calls `enrich_streamcat()` against
  real assets.

## Stub

Scaffolded with the right shape but the logic is heuristic or
placeholder-grade.

- **`src/aguayluz/confidence.py`** — tier-anchored base (T1=80…T4=30) with
  fixed deductions for partial coverage and missing coords. Not
  data-driven; calibrating against a held-out PR audit would improve
  scoring.
- **`ingest/frs.py:infer_asset_type()`** — name-keyword heuristic. Works on
  English + a handful of Spanish keywords (PRASA, LUMA, EBAR, embalse,
  lago). Misses any asset whose name doesn't contain a known keyword
  (e.g. unbranded substations). A learned classifier would lift the
  ~60% utility-detect rate seen in the live Bayamón pull.
- **HIFLD client fallback URLs** — `LAYER_URLS` in `hifld_client.py` were
  drafted from memory; the live `services1.arcgis.com` endpoints intermittently
  404 (this drove the fallback design). Confirming current URLs against
  the HIFLD hub would let live mode work without committed snapshots.
- **No notification confirmation loop** — the M23 Slack notifier posts on
  drift but there's no way to acknowledge ("Yes, I saw this; tracking it
  in PR #N"). For now, operator workflow is: see Slack ping → check the
  CI run → open PR per the runbook. Acknowledgement bot is a future M24+.

## Missing

Declared in the skill spec or schema enums but no producer emits the value.

- **`service_event.event_type` enum** includes `outage`, `restoration`,
  `boil_water`, `service_interruption` — only `project_update` is emitted
  by the FEMA adapter. A real-time outage scraper (PR.gov press feed, LUMA
  outage portal) would populate the others.
- **`aguayluz_bridge_summary.infrastructure_dependencies`** — populated by
  M7's `build_dependency_graph.py` but not surfaced into the handoff
  payloads. The spec implies receivers should be able to query it; M15
  could enrich `payload.bridge_summary` further.
- **`AYL_TRACK_TIME_SERIES` integration into vector scripts** — M14
  scripts work standalone, but the existing M5/M6/M7/M8/M13 vector scripts
  don't auto-snapshot. The plan called for a `--snapshot` flag on each;
  this is the cleanest remaining wiring task.
- **Live HIFLD URL confirmation** — see Stub above.
- **PR.gov + USGS event sources** — discussed in the M16 docs as future
  work; no adapter exists.

## Dead

Code that exists but no path reaches it.

- None detected. `ruff check .` passes (it catches unused imports + dead
  variables), the drift guard catches stale doc references, and every CLI
  subcommand is invoked at least by its own test path.

## Inventory

These counts are regenerated by `python scripts/gap_audit.py`. CI fails on
PRs that change them without committing the update.

<!-- gap-counts-begin -->
| Inventory | Count |
|---|---|
| `analysis_modules` | 4 |
| `cli_subcommands` | 15 |
| `ingest_adapters` | 7 |
| `schemas` | 15 |
| `scripts` | 20 |
| `test_files` | 29 |
| `waters_endpoints_wrapped` | 6 |
<!-- gap-counts-end -->
