# ADR 0003 — Durable monthly EIA acquisition checkpoints

Status: bounded implementation; full platform **NOT CERTIFIED**.

## Contract and user workflow

Electricity → Source acquisition exposes creation, progress, step/retry,
cancellation, paginated history and JSON export for monthly PR research jobs.
English/Spanish controls expose metadata, PR facet coverage and source-page
phases. Failure, unknown total and true zero source rows are distinct. Jobs do
not insert measurements, claims or canonical records. A complete job is an
AUDIT_ONLY acquisition, not scientific acceptance or live telemetry.

Additive API under `/electricity/v1/acquisition-jobs`:

- `GET ?offset=0&limit=50`: creation-ordered jobs, total and next offset;
  maximum 100 per page. Appending events to an older job does not reorder pages.
- `GET /{job_id}`: validated checkpoint state and immutable transition history.
- `POST`: idempotent creation with a 32-character hexadecimal request ID,
  allowlisted route (`facility-fuel` or `retail-sales`), source data column,
  declared geography facet, inclusive source months, page size and page limit.
- `POST /{job_id}/step` and `/cancel`: expected version required. Stale or fenced
  edits return 409, unknown jobs 404, invalid inputs 422 and corrupt evidence or
  storage 503. Every write uses the existing fail-closed operator authentication.

The versioned JSON schema describes list responses, job views, history and
request/command types. Existing projection v1, review contracts, scientific
revision behavior, Federation exports and dependency locks remain unchanged.
Acquisition appends source receipts and therefore legitimately advances the
scientific projection's source-content revision; it does not add observations.

## Persistence and crash recovery

`acquisition.sqlite3` contains append-only job snapshots, sequential versions and
chained event digests. SQLite triggers refuse update/delete; reads validate the
chain and immutable job specification. Read-only history never creates a ledger.
Local checksums are not protection against a privileged full-chain rewrite.

Each step first acquires a versioned five-minute lease in an immediate
transaction, then releases the SQLite lock before network I/O. At most one lease
can advance a given version. Each step makes one bounded metadata/facet/page
operation through the existing EIA client's size/time/retry and redaction limits.
The lease token is private. Expiry and whether recovery/cancellation are possible
are exposed to the GUI; expired workers cannot commit after a newer lease.

Cancellation immediately revokes the checkpoint lease. It does not promise to
abort a socket already waiting on the remote source or existing bounded retries.
A late response can remain preserved as raw evidence, but cannot advance the
cancelled job. Unexpected process/storage failure can leave RUNNING history;
after expiry, a new process revalidates and resumes the last committed checkpoint.

Original response bytes and credential-free receipts are committed before the
job checkpoint. A crash between these commits may leave additional captured
evidence, never an offset that skips uncaptured rows. Retry re-fetches that page;
the immutable source store handles content-addressed replay. Successful pages,
metadata and PR coverage survive subsequent failures and process restart.

Every read/resume replays all admitted checkpoints from source bytes, hashes,
URLs, request parameters, metadata/facet validations, page totals, scoped rows and
fingerprints. Changed totals, incomplete pages, repeated pages, exact repeated
rows and out-of-scope months/geography fail without advancing offsets. Repeated
rows remain preserved in raw captures; they are not silently deduplicated or
treated as entity-identity evidence. Page/row limits bound each job.

The source API is not assumed to provide a point-in-time snapshot: equal-count
upstream revisions can occur during offset pagination. This tranche does not
establish revision consistency, original PR route coverage, scientific units or
license acceptance from fixtures. Those gates remain open until real metadata,
original sources and independent reconciliation are available.

## Security and scope

No arbitrary URLs, query strings, credentials, roles or filesystem paths enter a
job specification. Runtime EIA/operator credential values are refused in specs.
Credentials are read by the existing EIA client from runtime environment only;
raw responses containing that credential are refused. Errors persist bounded
codes, not HTTP exceptions, URLs with query keys or arbitrary provider text.
Shared operator authentication is not individual identity or full RBAC.

The GUI polls durable state and manually advances bounded steps. This is not a
background scheduler, streaming telemetry subscription or automatic incremental
revision reconciler. Those remain explicit A.4/A.5 implementation gaps. Quotas,
large-history performance and production durability acceptance remain open;
history reconstruction currently trades throughput for fail-closed validation.

## Verification and recovery

Tests use explicit synthetic sources only. Backend tests cover restart/backup,
concurrent leases, expiry, stale versions, cancellation fencing, retry,
post-capture storage failure, source integrity, duplicate/overlapping pages,
missing credentials, unsupported PR coverage and true zero row accounting.
Frontend/E2E tests exercise actual API workflows in a disposable runtime,
source failure/retry, cancellation while a page is in flight, export/reload,
unauthorized writes, integrity failure/recovery, and bilingual accessibility.
Test-only mock transports are installed by the fixture server; there is no
production mock-provider switch.

Quiesce writers and back up every present electricity ledger: `ledger.sqlite3`,
`reviews.sqlite3`, **and** `acquisition.sqlite3`, using SQLite backup APIs along
with verified raw blobs. Restore to a new directory and compare scientific,
review and job revisions/counts. A restored active lease retains its original
expiry; wait for expiry or explicitly cancel before recovery. Keep later live
evidence. Older releases can ignore the additive job ledger without deleting it.
Production-equivalent restore, performance and device gates remain unverified.

One-line a-Shell-compatible bounded check, dependencies preinstalled:

`python3 -m pytest -q tests/test_electricity_jobs.py tests/test_electricity_reviews.py tests/test_electricity.py tests/test_electricity_capture_recovery.py tests/test_schemas.py`

Physical iOS execution is unverified. Browser workflow:
`npm --prefix dashboard run test:electricity-jobs`. Keep existing GUI seed runs
sequential with repository output validation; never lower coverage or regenerate
parity baselines to obtain passing results.
