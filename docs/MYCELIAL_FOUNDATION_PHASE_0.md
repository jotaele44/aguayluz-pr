# Mycelial research foundation — Phase 0 v0.2

Status: **research-only fungal occurrence evidence foundation**.

The project umbrella remains `research.mycelial`, but the persisted evidence
contract is `FungalOccurrenceRecord`. A fungal occurrence does not prove a
mapped underground mycelial network.

## Runtime boundary

The implementation remains outside production discovery roots under:

```text
research/mycelial/
```

The opt-in ASGI entrypoint is:

```text
research.mycelial.app:app
```

`create_app()` builds an independent FastAPI application. Importing the
research entrypoint does not import, mutate, or add routes to
`server.backend.app:app`.

The only routes are:

- `GET /research/mycelial/status`
- `GET /research/mycelial/analytics/{capability}`

Every analytics route returns HTTP `503` with `model_not_calibrated`.

## Canonical evidence contract

Every occurrence is validated against
`schemas/fungal_occurrence.schema.json` using Draft 2020-12 and format
checking before persistence.

The schema separates:

- evidence tier: `T1`–`T4`;
- review state: `accepted`, `needs_review`, `rejected`, or `blocked`;
- taxonomic confidence;
- temporal precision and validated date representation;
- coordinate confidence, datum, method, and uncertainty in metres;
- sensitivity status.

Coordinates are either complete with quantitative uncertainty or absent with
unknown coordinate metadata.

## Exact replay and duplicate candidates

Two identities are intentionally separate:

1. **Source-record identity** provides exact rerun idempotency.
2. **Duplicate-candidate identity** excludes source-specific identifiers and
   can link comparable cross-source assertions for review.

Candidate links are immutable events. They do not merge corroborating
assertions and do not decide which assertion is correct.

## Append-only persistence

SQLite triggers deny `UPDATE` and `DELETE` on:

- source records;
- occurrences;
- duplicate links;
- adjudications;
- policy decisions;
- dataset registrations;
- import receipts;
- supersessions.

Corrections are represented by new immutable events.

## Supersession

A supersession event records a predecessor, successor, actor, reason,
policy basis, and timestamp.

The append function requires both occurrences to exist, rejects
self-supersession, rejects multiple successors or predecessors, and prevents
cycles. Effective-state resolution follows the chain deterministically while
preserving all historical assertions.

## Import transactions and receipts

An import executes occurrence inserts, duplicate-candidate links, and its
receipt in one transaction.

- Validation rejects produce a `partial` receipt while committing accepted
  records and the receipt atomically.
- Unexpected failures roll back occurrence and link writes, then append an
  immutable `failed` receipt before raising `ImportFailedError`.
- Reusing the same run ID with the same source and input digest returns the
  existing receipt.
- Reusing it with different input fails closed.

## Sensitive coordinates

`safe_fungal_occurrence_view()` denies exact sensitive coordinates by default.
It accepts no authorization boolean. Exact disclosure requires an immutable
policy-decision ID whose subject, policy, and outcome authorize that specific
occurrence.

This helper does not create a public occurrence endpoint.

## Explicitly prohibited

Phase 0 cannot generate:

- habitat suitability;
- ecological connectivity;
- mushroom-location ranking;
- public exact sensitive coordinates;
- fungal-to-infrastructure inference;
- notifications;
- control actions.

Fungal, moisture, or substrate evidence must not be transformed into claims
about tunnels, pipelines, vents, military facilities, anomalous corridors, or
other concealed infrastructure.

## Scientific gaps that continue to block analytics

1. Verified Puerto Rico occurrence records with taxonomic evidence.
2. Sampling-effort and observer-bias representation.
3. Taxon- or guild-specific literature parameters.
4. Puerto Rico sensitive-taxon disclosure policy.
5. Structured positive and negative field surveys.
6. Date-matched environmental predictors.
7. Substrate, host, deadwood, and microsite observations.
8. Independent validation of ecological connectivity hypotheses.
9. Calibration objectives and threshold-selection procedure.
10. External validation data independent of training data.
