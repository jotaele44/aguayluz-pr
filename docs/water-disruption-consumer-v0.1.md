# Water-disruption consumer contract v0.1

## Consumer API

| Method | Path | Purpose |
|---|---|---|
| POST | `/water-disruption/intake` | Idempotently accept a Centinelas candidate envelope |
| GET | `/water-disruption/intake/{candidate_id}` | Receipt, schema, and validation state |
| GET | `/water-disruption/validation-queue` | Pending domain decisions |
| POST | `/water-disruption/validation/{candidate_id}` | Record append-only validation decision |
| GET | `/water-disruption/incidents` | Canonical incidents and filters |
| GET | `/water-disruption/incidents/{incident_id}` | Evidence graph and lifecycle |
| POST | `/water-disruption/incidents/{incident_id}/transition` | Apply valid lifecycle transition |
| POST | `/water-disruption/incidents/{incident_id}/merge` | Merge with provenance |
| POST | `/water-disruption/incidents/{incident_id}/split` | Split with provenance |
| POST | `/water-disruption/retractions` | Apply producer correction/retraction |

All writes require idempotency keys. The intake response includes envelope hash, receipt ID, schema decision, and whether the payload was newly stored or replayed.

## Queues

1. `candidate_intake`: integrity and schema checks.
2. `validation_queue`: relevance, location, infrastructure, freshness, and corroboration.
3. `incident_resolution`: deterministic match, merge, or new-incident proposal.
4. `lifecycle_updates`: repair/restoration/status claims awaiting validation.
5. `retraction_queue`: correction impact analysis.
6. `notification_outbox`: alerts, maps, exports, and federation updates.
7. `dead_letter`: unsupported schema, broken provenance, invalid transition, or integrity failure.

## Promotion policy

A candidate cannot become `confirmed` merely because `confidence.overall` exceeds a threshold. Confirmation requires authoritative support, or two independent sources plus reviewer approval. Unresolved locality, stale reports, private plumbing, customer-account shutoffs, and private cistern failures remain unverified or rejected.

## Test matrix

| Area | Required cases |
|---|---|
| Intake | valid envelope; replay; changed payload under same ID; missing evidence; unsupported version |
| Promotion | official scoped source; two-source approval; one eyewitness; high-confidence-only rejection |
| Domain gate | public main vs building plumbing; public outage vs account shutoff; restoration vs stale repost |
| Dedup | replay stability; overlapping incidents; same municipality/different asset; merge/split provenance |
| Lifecycle | allowed transitions; invalid skip; partial restoration; restored/closed; reopened event |
| Retraction | source correction; sole support removed; conflicting support remains; alert/export correction |
| GIS | exact/approximate/unresolved locations; no fabricated geometry; method provenance |
| Accounting | every received candidate has receipt and terminal queue state |
| API/GUI | queue/detail/evidence/decision/merge/split/transition/retraction/map workflows and failure states |
| Federation | only policy-eligible truth states exported; corrections and restoration propagated idempotently |

## Implementation sequence

1. Validate the producer fixture against both repository copies of v0.1.
2. Add immutable intake receipts and envelope-hash idempotency.
3. Implement validation policy as a versioned pure-domain function.
4. Implement deterministic incident matching and append-only lifecycle events.
5. Add restoration, correction, merge, and split operations.
6. Correlate, but do not conflate, reporting incidents with existing sensor alert operations.
7. Add API endpoints and generated clients.
8. Add discoverable validation, incident, evidence, and map GUI workflows.
9. Run shadow ingestion with exports and notifications disabled.
10. Activate only after no-unverified-promotion, replay, transition, source-accounting, restoration, and retraction tests pass.

## Release gates

- zero direct candidate-to-confirmed bypasses;
- deterministic receipts, incident IDs, and dedup decisions on replay;
- 100% candidate accounting from intake through terminal queue state;
- append-only evidence, validation, lifecycle, merge/split, and retraction history;
- complete restoration and correction propagation;
- backend/API/client/component/discoverable-GUI parity;
- production notifications remain disabled until shadow-run false-positive and missed-event review is accepted.
