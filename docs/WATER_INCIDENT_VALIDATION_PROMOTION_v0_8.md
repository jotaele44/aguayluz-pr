# Water incident validation promotion v0.8

## Defect

A candidate first validated as `unverified` created a canonical incident with `truth_state=unverified` and `lifecycle_state=reported`. A later authoritative validation persisted a `confirmed` validation event, but `resolve_incident()` returned the existing incident without reconciling the stronger decision.

## Repair

The canonical base incident remains immutable. Current truth is now derived from an append-only `incident_truth_events.jsonl` stream.

Truth strength is monotonic during normal validation:

`unverified < corroborated < confirmed`

A stronger validation appends a truth event linked to its `validation_id`. Promotion to `confirmed` also appends a lifecycle event with reason `validation_promotion`. Weaker subsequent validations remain in the validation ledger but cannot downgrade the canonical current view.

Retraction is separate from normal validation strength. It appends a truth event to `retracted` and an allowed lifecycle transition without editing prior incident, validation, or evidence records.

## Idempotency

Validation idempotency keys are bound to a digest of the candidate, decision, and reviewer. An exact replay returns the original validation event. Reusing the key with changed validation content fails closed with `validation_idempotency_conflict`.

## Existing shadow ledger migration

No destructive migration is required.

For every existing incident:

1. Read its immutable `truth_state` as the initial truth state when no `incident_truth_events` exist.
2. Replay validation events for the incident candidate IDs in recorded order.
3. Append only stronger truth events, linking each to the originating `validation_id`.
4. When the strongest replayed result is `confirmed` and the current lifecycle is `reported`, `acknowledged`, or `disputed`, append one `validation_promotion` lifecycle event.
5. Do not rewrite `incidents.jsonl`, `validation_events.jsonl`, evidence, or intake receipts.
6. Replaying the migration must produce no additional events after the first successful pass.

The current shadow dataset can be regenerated from its synthetic input if desired, but the production-safe migration contract remains append-only.

## Safety state

- `shadow_mode = true`
- `notifications_enabled = false`
- `production_promotion_enabled = false`
- no live alerts
- no production export eligibility
