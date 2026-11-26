# Consolidated hydroelectric history milestone

State: SOURCE_FEASIBILITY_BLOCKED / NOT_CERTIFIED.

The selected deliverable is plant-level Puerto Rico hydroelectric history for
January 2016–December 2025, with a bilingual native explorer and actual persisted
THEHUB consumption. Aggregate-only data cannot close this milestone. The full
88-requirement ledger remains in docs/electricity/requirements.v1.json unchanged.
Additional workspace breadth is paused.

## Integration and preservation

The integration branch starts at verified electricity candidate
05f5aaeda789c9f6276fa9ccb8799a681e1c141f, already containing the complete electricity
stack. The checkpoint branch preserve/electricity-registry-05f5aae retains that
exact head. Earlier branches, commits, original checkout and THEHUB are preserved.
PR #394 is the single consolidated AguayLuz review surface. Its existing head
branch can advance only by fast-forward after the independent checkpoint is
published; the integration branch names the same candidate. No protected merge,
force-push or unrelated branch merge is authorized.

## Current source audit

Environment revision 37 is current and enforced. Its allowed hosts exclude EIA;
there are no configured secret bindings. The historical uploaded credential path
is absent. No actual credential was loaded, printed, hashed or transmitted.
Public original workbook downloads do not require an API key, but still require
approved host access. API metadata discovery additionally needs secure runtime
injection of a rotated credential. No alternate proxy or remote runner was used
to circumvent the enforced policy.

The bounded local ZIP inventory contains research inputs, not independently
verified original plant-month records for the requested decade. Original RC8–RC14
and the named scaffold are still unavailable. The finite returned changed files
of current hydro PR #392 contain no original workbook or acquisition receipt.
This does not establish absence outside the inspected locations.

Source feasibility is BLOCKED_EXTERNAL_DEPENDENCY. Verified original artifacts,
plant identities and plant-month observations are currently zero for this
milestone; the true plant population and coverage denominator remain unknown.
The requested 120 calendar months are not a verified source-data denominator.
No plant roster, zero generation values or historical measurements were invented.

## Hydro PR #392 overlap decision

Reviewed head: 5c215ce21a0d9bd67bc6ba403c29105bd4eda590. Acquisition/discovery modules
and source definitions were read at their exact Git blob identities, recorded in
hydro-overlap-inputs.v1.json. This supersedes the earlier f1bdf7e7 snapshot review.

| Concern | Current electricity foundation | Hydro draft | Decision |
|---|---|---|---|
| Immutable raw bytes | Atomic content-addressed store with SQLite receipt history | Separate source/hash folders and JSON receipts | Retain electricity store; no second store |
| Transport and provenance | Guarded EIA client, redacted bounded status, request metadata | Source-agnostic fetch and independent receipt shape | Retain guarded EIA path; no automatic merge |
| Retry/checkpoints | Durable fenced jobs, cancellation and native health workflow | Independent retry/result log and link discovery | Reuse concepts only after original-source audit; no parallel scheduler |
| Source semantics | Candidate claims, explicit classes and blocked promotion | Declared source priorities and discovery candidates | Definitions are research inputs; discovery is not verified coverage |

No hydro acquisition code was imported or executed. No new acquisition code was
added. This is a structural overlap decision, not a formal security acceptance.

## Locked downstream work and acceptance

Once approved source access or official offline originals are available:

1. Freeze annual EIA-860/923 originals where documented PR plant-level coverage
   exists. Otherwise inspect original official PREPA/HydroCo plant-level records.
   Unsupported geography/granularity leaves acceptance blocked; no aggregate
   fallback or inferred plant allocation is allowed.
2. Build version-specific parsers against originals. Preserve literal IDs, source
   locators, decimal precision, units, publication revisions and reporting periods.
   Verify effective-dated crosswalks independently of names and geography.
3. Reconcile every plant-month in the requested period with explicit reported,
   zero, missing, suppressed, unresolved or documented out-of-scope states. Keep
   contradictions and superseded manifestations visible. Missing values stay gaps.
4. Freeze aguayluz.electricity-history/v1 and its versioned read-only history APIs
   only after source shape is known. Existing contracts remain unchanged. Native
   English/Spanish chart/table, comparison, provenance and complete CSV/JSON export
   must all read the same immutable snapshot. No live labels or unsupported
   capacity factors are permitted.
5. Develop the THEHUB adapter in an isolated branch from a freshly verified head.
   Persist exact producer revisions in dedicated historical records, expose a
   read-only AguaYLuz historical view and test restart/retrieval against original
   export bytes. The existing service-event promotion workflow cannot substitute
   for historical acceptance. THEHUB currently remains unchanged.
6. Require original-row/count/total reconciliation with zero unexplained residue,
   full regression, bilingual desktop/mobile/keyboard checks, exact-byte consumer
   acceptance, separately attributed scientific review and hash/count-preserving
   restore. Overall certification remains closed while any required gate is open.

## Why dependent implementation is paused

The approved plan explicitly says: if no authoritative plant-level dataset is
obtainable, keep dataset acceptance blocked and complete only consolidation,
source auditing and recovery work. That source-first condition applies now.
No placeholder explorer, speculative parser, synthetic production dataset or
mock consumer was added. This is a blocked milestone, not completed delivery.

The unblock is approved EIA host access plus secure API credential injection when
needed, or official original offline files with provenance. Offline operator
assertion alone does not establish independent source verification. Production
credential rotation and independent scientific review remain separate gates.
