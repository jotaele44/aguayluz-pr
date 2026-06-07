# Contributing

Three repeatable patterns: adding an ingest adapter, adding an analyzer,
adding a schema. The federation gates (G01–G08) catch drift in all three.

## Add a new ingest adapter

Pattern lifted from `src/aguayluz/ingest/frs.py` and `src/aguayluz/ingest/hifld.py`.

1. **Adapter module** under `src/aguayluz/ingest/<source>.py`:
   - `parse_<source>_response(envelope) -> list[FacilitySeed]` (assets) or
     `list[EventSeed]` (events).
   - Use `infer_asset_type(name)` from `frs.py` for consistent classification
     (water/wastewater/power/telecom/fuel/unknown), or write a specific
     classifier if your source has a more authoritative type column.
   - Stamp `source_provenance` so the source manifest can attribute records.
   - Mark non-utility records `is_utility=False` — they get skipped by the
     pipeline.

2. **HTTP client** under `src/aguayluz/ingest/<source>_client.py` (skip if your
   source only ships static GeoJSON/CSV files):
   - Wrap `httpx.Client`. Pass `timeout=DEFAULT_TIMEOUT_S` + `User-Agent`.
   - Retry 5xx via `max_retries`; raise on 4xx immediately.
   - Try-live-then-snapshot fallback if the source URL is flaky (see
     `hifld_client.py`).

3. **Script wiring**: extend `scripts/ingest_facilities.py` or
   `scripts/ingest_events.py` with a `--source <yours>` branch. Add a
   `_live_seeds()` branch if you ship a client. Existing
   `ingest_seeds()`/`ingest_event_seeds()` consumes your seeds unchanged.

4. **CLI subcommand** in `src/aguayluz/cli.py` — copy the `ingest-frs` pattern.

5. **Fixture** under `tests/fixtures/<source>/`:
   - Include both representative valid records AND your source's edge cases
     (null fields, non-utility records, encoding quirks).

6. **Tests** under `tests/test_ingest_<source>.py`:
   - Parser: full fixture coverage + classification matrix + empty response.
   - Client (if applicable): URL construction, 5xx retry, 4xx raise,
     dedupe, pagination.
   - Optional: live test under `tests/test_live_ingest.py` gated by an env var.

## Add a new analyzer

Pattern lifted from `src/aguayluz/analysis/dependency.py`,
`reconciliation.py`, `watersheds.py`.

1. **Analyzer module** under `src/aguayluz/analysis/<name>.py`:
   - Function takes already-validated entity dicts (`assets`, `events`,
     `findings` as relevant) + injectable `snap_fn` for any external calls.
   - Returns `(records, review_items)` or `(nodes, edges)` — never writes
     files.

2. **Schema** for the analyzer's output entity (if it's a new shape). See
   `docs/schemas.md` for the gate-G01 registration trail.

3. **Vector script** under `scripts/<analyzer>.py`:
   - Read prior outputs/. Call analyzer. Validate records against the
     schema. Write `outputs/<entity>.json`.
   - Refresh `outputs/integration_report.json` and
     `outputs/base44_export.json` (use `build_base44_envelope()`).
   - Demo mode injects a fixture-driven `snap_fn`; live mode wires a real
     client with `--max-calls` cap to protect the WATERS rate budget.

4. **CLI subcommand** in `src/aguayluz/cli.py`.

5. **Tests** under `tests/test_<analyzer>.py`:
   - Happy path on representative entity dicts.
   - Each finding/edge kind with a dedicated test.
   - Failure routing: missing inputs, snap exceptions, empty responses →
     review queue.
   - Schema round-trip.

## Add a new schema

See "Adding a new schema" at the bottom of `docs/schemas.md`. Six steps,
all mechanical. The drift guard in `tests/test_docs.py` (added in M16) will
fail CI if you add a schema without updating the docs.

## Live tests

Live tests (FRS, FEMA, HIFLD, WATERS) are gated by env vars so CI never
accidentally hits the live APIs. The conventions:

- `EPA_LIVE_TESTS=1` enables `tests/test_live_ingest.py`.
- `EPA_WATERS_API_KEY` or `API_DATA_GOV_KEY` enables
  `tests/test_navigation_live.py` and `tests/test_smoke.py`.

When writing a live test:
- Decorate with `pytest.mark.live` so they're discoverable as a group.
- Skip cleanly via `pytestmark = pytest.mark.skipif(...)` at module top.
- Bound API calls to ~1–2 per test (free-tier api.data.gov budget is
  1000/hr).

## Federation gates (G01–G08)

The eight gates in `src/aguayluz/validation.py` mechanically enforce the
skill spec's rules. Run `python scripts/validate_repo.py` after every
change. If you break a gate, the script exits 1 and CI fails. Don't
disable gates to make tests pass — the gate is right; the test is wrong.

## Running the test suite

```
.venv/bin/python -m pytest -q              # offline (~200+ tests)
EPA_LIVE_TESTS=1 .venv/bin/python -m pytest -q tests/test_live_ingest.py
EPA_WATERS_API_KEY=… .venv/bin/python -m pytest -q -m live
```

## Style

- `ruff check .` must pass. Per-file overrides live in `pyproject.toml`
  (e.g. Typer's `B008` idiom in `cli.py`, `B011` in tests).
- Python 3.10+ minimum.
- No `from __future__ import annotations` exceptions — they're already on
  in every module.
- No new dependencies without a paragraph rationale in the PR.
