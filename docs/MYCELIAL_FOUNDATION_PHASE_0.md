# Mycelial research foundation — Phase 0

Status: **research-only, evidence-management foundation**.

Phase 0 can ingest, normalize, deduplicate, adjudicate, and register fungal occurrence evidence. It cannot generate habitat suitability, mushroom-location rankings, connectivity maps, public exact coordinates for sensitive taxa, infrastructure inferences, notifications, or control actions.

## Runtime boundary

The bounded ASGI entrypoint is:

```text
server.backend.app_mycelial:app
```

It adds:

- `GET /research/mycelial/status`
- `GET /research/mycelial/analytics/{capability}` — always HTTP 503 with `model_not_calibrated`

The standard application is not silently altered while the feature is under draft review.

## Persistence contract

`initialize_database()` creates append-only logical ledgers for:

- source records;
- occurrences;
- duplicate links;
- adjudications;
- policy decisions;
- dataset registrations;
- immutable import receipts.

Existing rows have no update or delete API. Corrections are represented by new adjudication or policy-decision rows.

## Evidence confidence dimensions

Every occurrence separates:

- evidence tier: `T1`–`T4`;
- taxonomic confidence;
- coordinate confidence;
- temporal confidence;
- review status;
- sensitivity status.

A high-confidence value in one dimension does not promote another dimension.

## Determinism and deduplication

The canonical JSON payload is key-sorted and uses normalized, deduplicated evidence references. SHA-256 of that payload is the record fingerprint. Duplicate fingerprints and duplicate occurrence IDs are blocked and reported in the import receipt.

## Sensitive coordinates

Sensitive records retain exact coordinates only in the authorized ledger. `safe_occurrence_view()` removes latitude and longitude unless the caller is explicitly authorized.

## Data gaps that remain blocking for analytics

1. Verified Puerto Rico occurrence corpus with taxonomic evidence.
2. Sampling effort and observer-bias representation.
3. Taxon/guild-specific literature parameters.
4. Puerto Rico sensitive-taxon disclosure policy.
5. Structured positive and negative field surveys.
6. Date-matched environmental predictors.
7. Substrate, host, deadwood, and microsite observations.
8. Independent validation of any ecological connectivity hypothesis.
9. Calibration objectives and threshold-selection procedure.
10. External validation set independent of training data.

Closing these gaps is not a prerequisite for Phase 0 ingestion. It is a prerequisite for activating ecological analytics.

## Explicitly rejected inference chain

Fungal occurrence or moisture evidence must not be transformed into claims about tunnels, pipelines, vents, military facilities, anomalous corridors, or other concealed infrastructure. Such outputs are outside this module's scientific contract.
