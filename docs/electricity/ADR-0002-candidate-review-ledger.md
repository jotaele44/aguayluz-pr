# ADR 0002 — Reversible candidate review recommendations

Status: implemented bounded development capability; **NOT CERTIFIED**.

The electricity evidence inspector needs an attributable, reversible way to
record research recommendations without changing source claims, contradictions,
scientific projections or canonical truth. Original EIA and RC8–RC14 acquisition,
independent scientific acceptance and individual operator identity remain open.

## Decision

Add a separate append-only `reviews.sqlite3` in the electricity runtime directory.
`GET /electricity/v1/reviews` supplies the versioned
`aguayluz.electricity-reviews/v1` contract. `POST` to the same path requires the
existing fail-closed operator authentication. The original electricity projection
v1 schema, scientific revision algorithm and existing Federation exports remain
unchanged. The separate root schema also defines `ReviewRequest` for POST.

Each event references the complete validated claim's SHA-256, source receipt,
source identity, source projection revision, prior review revision, bounded reason
code, server timestamp, idempotency request ID and authenticated role. A receipt
hash is not a row identity: multiple generator claims can share the same source
bytes. Literal generator IDs such as `01` and `1` remain distinct.

Actions are `RECOMMEND_RETAIN`, `RECOMMEND_EXCLUDE`, `DEFER` and `REVERSE`.
Recommendations are advisory. They neither remove a claim nor resolve a
contradiction or promote data. Every event and scientific claim stays AUDIT_ONLY;
canonical promotion remains BLOCKED. There is no identity/crosswalk edit or
connectivity inference in this workflow.

Reversal appends an event referencing the selected claim's current active
recommendation. It exposes the previous active recommendation, if any. Reversing
an overridden event, another claim, an already reversed event or a reversal event
is refused. The history remains inspectable and exportable in the native GUI.

## Concurrency and integrity

Writes use a SQLite immediate transaction. The expected source and review
revisions must agree with the admitted snapshot. Competing review edits from the
same expected head allow one append; subsequent requests receive a redacted 409
and the GUI refreshes history. Source evidence is immutable, so an event can
remain bound to its admitted source revision when later evidence is appended.
Source and review databases do not form a distributed or cross-database write
transaction; this feature never claims otherwise.

An exact request ID/body retry returns the existing event even after later
source/review appends. Reusing an ID with another body is refused. The GUI keeps
the pending request in memory across an uncertain transport failure; changing
the recommendation or explicitly refreshing starts a new intent. Reloading the
browser discards the pending client request; operators should inspect durable
history before resubmitting after a reload.

Read-only history opens never create databases. Each read checks sequence,
idempotency uniqueness, event digests, prior hashes, full claim references and
reversal consistency. Source evidence integrity is checked before review access.
Corrupt history fails closed independently of the original scientific projection.
SQLite triggers refuse normal update/delete, and symlink databases are refused.
These are local integrity controls, not externally witnessed signatures: a
privileged host administrator rewriting an entire valid chain or truncating its
tail is outside this checksum guarantee. External anchoring remains open.

## Authorization and limitations

The existing shared operator secret provides a role boundary. Events truthfully
record `SHARED_OPERATOR_KEY`, and the projection discloses that this is not an
individual reviewer identity. The GUI does not supply an actor field. Individual
identity, per-person RBAC, reviewed canonical adjudication policy, free-text
documented scientific findings and independent decision acceptance are not
implemented by this tranche. B.9 remains PARTIALLY_IMPLEMENTED.

Reason codes are enumerated, avoiding arbitrary request/exception text in the
review ledger. Real credentials never appear in source, event records, error
details or test artifacts. Test role strings are explicit synthetic fixtures.

## GUI and tests

The visible Electricity → Evidence inspector path exposes exact-claim selection,
recommendation/reason controls, current recommendation, durable event history,
safe conflict refresh, retry and JSON export. All controls have English/Spanish
labels; unavailable or incoherent history disables writes/export. No canonical
scientific decision can be made through presentation state.

`tests/test_electricity_reviews.py` covers literal/full-claim identities,
source preservation, reversible history, stale revisions, idempotency,
concurrency, immutable/corrupt/symlink/orphan negatives, auth, contract validation,
failed inserts and two-ledger restore. Frontend tests cover exact request binding,
uncertain retry, conflicting edits, unavailable states, authentication failure
and bilingual automated accessibility.

`dashboard/tests/electricity-review.spec.mjs` runs against an actual backend in a
disposable temporary runtime seeded only with explicitly synthetic SOURCE_CANDIDATE
claims. No measurements are seeded. It exercises authorized recommendation,
reversal, export, reload, mobile Spanish, unauthorized writes, actual concurrent
edits and injected read failure followed by real producer retry. It cannot
establish scientific correctness of an official source or production deployment.

## Recovery

Quiesce writers and back up **both** `ledger.sqlite3` and `reviews.sqlite3` with
SQLite's backup API, together with verified raw blobs and their receipt hashes.
Restore into a new directory. Compare both scientific and review revisions,
claim/event counts and complete source hashes; preserve later live evidence.
Older candidates can ignore the separate review ledger without deleting it.
A Git checkout cannot restore these rows. The bounded restore test is not a
production-equivalent recovery-time or durability certification.

One-line a-Shell-compatible local check, with dependencies already installed:

`python3 -m pytest -q tests/test_electricity_reviews.py tests/test_electricity.py tests/test_electricity_capture_recovery.py tests/test_schemas.py`

Browser check: `npm --prefix dashboard run test:electricity-review`. Physical iOS
execution, pinned-browser availability and operational restore remain separate
gates. Run full Python/repository checks sequentially with the existing GUI seed
harness. Never lower coverage, regenerate the parity baseline, alter source pins
without verification or change fixtures merely to manufacture a PASS.
