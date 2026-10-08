# Real-time data acquisition audit — 2026-09-23

## Scope

A full discovery pass over every mechanism in this repo that acquires data in
real time or near-real time, to find workflow optimizations. Complements
`REFRESH_AUTOMATION_AUDIT_2026-08-17.md`, which audits alert-lifecycle
semantics of the same `refresh` workflow; this audit covers the acquisition
mechanisms themselves (transport, cadence, retry, freshness, caching), not
alert-delta semantics.

## Summary finding

Despite README language about "real-time" hazard feeds, this repo has **no
push-based or streaming acquisition** — no WebSocket, MQTT, Kafka, pub/sub, or
sensor/hardware ingestion. What exists is:

1. A GitHub Actions cron pipeline (`*/15 * * * *` / daily / weekly) polling
   ~50 public REST APIs.
2. One genuine Server-Sent Events endpoint (`/events/stream`) whose
   underlying data, before this audit, was frozen at server startup.
3. Dashboard polling via TanStack Query `refetchInterval`.

`src/aguayluz/neon/client.py` is the one HTTP client in the repo that
retries transient failures with exponential backoff and honors
`Retry-After` — every other ingest script did a single-attempt request with
no retry, which is the majority of the findings below.

## Mechanisms found

| Mechanism | Location | Cadence | Data |
|---|---|---|---|
| GH Actions cron "fast" | `.github/workflows/refresh.yml:4`, `scripts/refresh.py` `PLANS["fast"]` | every 15 min | NWS alerts, NHC storms, USGS quakes/continuous/RTFI, NOAA tides |
| GH Actions cron "daily"/"weekly" | `refresh.yml:6-7` | daily 07:00 UTC / Monday 07:00 UTC | USGS levels/groundwater/metadata/etc., NEON, drought, precip, EPA/OSHA/FEMA |
| LUMA/MiLUMA live outage fetch | `scripts/fetch_luma_live.py` | previously only manual `--all` dispatch | municipality + regional power-outage status |
| SSE `/events/stream` | `server/backend/main.py` | 5s push tick | latest 20 service/incident events |
| Dashboard polling | `dashboard/src/lib/hooks.js:13,37,59` | 15s / 60s / 30s | `/health`, `/outages/status`, `/system/status` |
| NEON client (reference pattern) | `src/aguayluz/neon/client.py` | daily/weekly | site/product availability |

## Findings and fixes applied

### F1 — No retry/backoff on fast-cadence ingest scripts
`ingest_usgs_quakes.py`, `ingest_nws_alerts.py`, `ingest_nhc_storms.py`, and
`ingest_noaa_tides.py` each did a single `httpx.get(...)` +
`raise_for_status()`. A transient timeout or 5xx from a government API —
common during the exact hazard events these feeds exist to catch, when
traffic to NWS/USGS spikes — failed the whole ingest step outright.
`ingest_usgs_continuous.py` and `ingest_usgs_rtfi.py` shared the same gap via
`src/aguayluz/usgs_water_api.py:iter_ogc_pages`.

**Fix:** extracted the NEON client's retry/backoff (exponential, jittered,
honors `Retry-After`, retries 429/5xx and transport/timeout errors) into
`src/aguayluz/http_retry.py`, applied at all five call sites. Tests:
`tests/test_http_retry.py`.

### F2 — LUMA live fetch had no retry either, and used a bespoke error path
`scripts/fetch_luma_live.py` used `urllib.request.urlopen` directly with a
single attempt. Unlike the httpx-based scripts, a 403 here is the expected,
non-transient Incapsula WAF block, so retrying it would waste the retry
budget on a failure mode that will never recover mid-run.

**Fix:** added a small retry loop in `_request_json` that retries only
transient failures (`URLError`/`TimeoutError`, 5xx) and never retries a 403
or a bad-JSON body. Tests: new cases in `tests/test_fetch_luma_live.py`.

### F3 — The most volatile source ran least often
Power-outage status changes on a minutes timescale, yet
`scripts/fetch_luma_live.py` and its downstream ingest chain
(`ingest_luma_status.py`, `derive_luma_status_changes.py`, `ingest_aee.py`)
were wired only into `PLANS["all"]` — manual `workflow_dispatch` only, not
the 15-minute cron.

**Fix:** added those four steps (already `optional=True`, so a WAF block
warns and continues rather than failing the cadence) to `PLANS["fast"]` in
`scripts/refresh.py`. Updated the `refresh.yml` fast-step name to reflect
it. Tests: `tests/test_refresh_plans.py` now locks the co-scheduling and
ordering invariants for both `fast` and `all`.

### F4 — `/events/stream` replayed a frozen snapshot, not live data
The SSE generator closed over the module-level `_events` list, built once at
import time (the code's own comment: "restart server to pick up data
changes"). The "Live Logs" dashboard page therefore re-received the exact
same 20 rows every 5 seconds until the backend process restarted — real-time
transport over a snapshot, not a real-time data source. The endpoint also had
no explicit client-disconnect check and zero test coverage.

**Fix:** added `_current_events()`, which re-reads the same event sources
from disk on each call (cheap after F5's caching); the SSE endpoint now
calls it instead of the frozen `_events` global, and checks
`request.is_disconnected()` each tick. Every other endpoint intentionally
keeps using the frozen `_events` snapshot — this fix is scoped to the one
endpoint whose entire purpose is to reflect new data without a restart.
Tests: `tests/test_backend_events_stream.py`.

### F5 — Every poll re-parsed JSONL corpora from disk
`_load_jsonl`/`_load_json` in `server/backend/main.py` re-read and
re-parsed their file on every call, with no caching. `/health` alone calls
`_load_jsonl` once per entry in `READINGS_FILES` (8 reading kinds) on every
request, and `app.py`'s `/readings`/`/monitoring/health` reuse the same
function. Combined with the dashboard's 15s/30s/60s `refetchInterval`
polling (`dashboard/src/lib/hooks.js`), this meant repeated full re-parses of
files that only change when the cron refresh job commits.

**Fix:** added an mtime-keyed cache to both functions — a cache hit when the
file's `st_mtime_ns` is unchanged, a re-parse (and cache update) otherwise.
No new dependency; safe for this single-process FastAPI deployment. Tests:
`tests/test_load_jsonl_cache.py`.

### F6 — No job timeout on the refresh workflow
The `refresh` job in `.github/workflows/refresh.yml` had no
`timeout-minutes`, so it inherited GitHub's 360-minute default.
`concurrency: cancel-in-progress: false` means runs queue rather than
overlap, so a single hung run could back up the 15-minute fast cadence for
hours.

**Fix:** added `timeout-minutes: 45` — comfortably above the heaviest
`--all` cadence's expected duration, far below the previous implicit
6-hour ceiling.

## Verification

- `pytest tests/test_http_retry.py tests/test_ingest_usgs_quakes.py tests/test_ingest_nhc_storms.py tests/test_ingest_noaa_tides.py tests/test_usgs_water_api_coverage.py tests/test_fetch_luma_live.py tests/test_refresh_plans.py -q`
- `pytest tests/test_backend_events_stream.py tests/test_backend_events_api.py tests/test_backend_readings_api.py tests/test_backend_alerts_api.py tests/test_server_smoke.py tests/test_load_jsonl_cache.py -q`
- `python scripts/refresh.py --fast --dry-run` shows the LUMA live chain now
  scheduled in the fast cadence.
- Full suite: `pytest -q`.
