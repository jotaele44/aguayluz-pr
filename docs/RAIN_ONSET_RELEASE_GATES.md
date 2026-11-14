# Rain onset notification release gate (v1)

## Scope and implementation
Pure detector: `src/aguayluz/rain_onset.py`. Regression suite: `tests/test_rain_onset.py`.
Detector output is an observation event, **not** an official NWS alert, not a certified municipality-wide rainfall determination, and not permission to push an emergency notification.

## Required prerequisites before production
1. Freeze authoritative precipitation feed with source URLs, UTC retrieval timestamps, sample cadence, gauge/radar station identifiers, raw payload hashes, source schema, and bounds.
2. Bind the station or radar polygon to municipality using independent spatial evidence; proximity alone is not sufficient.
3. Implement persistent per-stream state and an idempotent transactional outbox keyed by `event_id + channel + subscriber`; run replay, crash-restart and concurrent-worker tests.
4. Add controlled opt-in subscriptions; authenticate administrative changes and protect destination addresses and ntfy topics.
5. Wire only validated, active, non-expired observation events to existing notification infrastructure; official warnings remain separately classified.
6. Prove observed sensor timestamps, ingestion timestamps, event-confirmation timestamps and delivery receipt independently. Do not equate an HTTP request with receipt on iOS.
7. Dry-run first, enable production in stages, monitor false alarms, stale feeds, failures and duplicate notification counts, and prove rollback.

## Testing
From repository root with dependencies installed:

`PYTHONPATH=src python -m unittest discover -s tests -p 'test_rain_onset.py' -v`

Do not use an external test-domain URL in production: example.org in the test suite is a synthetic placeholder.

## Certification
- Code present: PASS (feature branch only).
- Positive/negative suite: OPEN (not executed in a verified CI or local runtime).
- Authoritative input acquisition: OPEN.
- Persisted restart-safe event state and delivery outbox: OPEN.
- Configured SMTP/ntfy destinations and opt-in: OPEN.
- Background scheduling / refresh orchestration: OPEN.
- Verified physical iOS delivery: OPEN.
- Deployment / rollback rehearsal: OPEN.
- Production release: BLOCKED.

No `main` branch changes, production configuration changes or deliveries are part of this change.
