# Electricity development and recovery

Release state: **NOT CERTIFIED**. Do not deploy, merge or promote this tranche.

## Validation

From the repository root with the development dependencies installed:

```sh
python3 -m pytest -q --cov
python3 scripts/validate_repo.py
python3 scripts/check_gui_parity.py
npm --prefix dashboard run lint
npm --prefix dashboard test
npm --prefix dashboard run build
npm --prefix dashboard run test:gui-parity
```

Run repository Python validation and GUI parity **sequentially**. The existing
browser harness seeds a review queue while running. It must not share that output
workspace with concurrent repository validation. Existing fixture isolation work
in PRs #362/#372 remains separately owned; this tranche does not transplant it.
Never rebaseline GUI parity or reduce the 80% Python coverage floor to obtain PASS.

One-line a-Shell-compatible bounded validation (dependencies must already exist):

`python3 -m pytest -q tests/test_electricity.py tests/test_schemas.py tests/test_federation_contract_compat.py tests/test_federation_evidence_state.py`

One-line dependency-free contract JSON readability check:

`python3 -c "import json,pathlib; s=json.loads(pathlib.Path('schemas/electricity_projection.v1.schema.json').read_text()); assert s['properties']['schema_version']['const']=='aguayluz.electricity-projection/v1'; print('JSON CONTRACT READABLE; NOT CERTIFIED')"`

These commands are syntactically a-Shell-compatible; execution on physical iOS
hardware is unverified. Browser GUI checks require desktop Node/Playwright.

The default browser gate retains pinned Playwright Chromium. In an environment
with a blocked browser download, an explicitly recorded local diagnostic may use
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium`. A system browser result is
not evidence that the pinned browser or desktop/iPhone package passed.

## Credentials and source failures

Set server-side `EIA_API_KEY` only via approved runtime injection. Rotate any
previously exposed credential before production. Do not paste credentials into
URLs, files, logs, PRs, exports, or frontend variables. `API_SECRET_KEY` controls
electricity acquisition/import; unset means writes disabled. The GUI uses the
existing System & Tools operator-key session configuration.

An EIA proxy denial, missing credential, absent PR facet, unsupported workbook,
missing source bytes, integrity mismatch, or incomplete page is not a zero value.
Preserve failure evidence, show the blocked state, and continue offline research.
Do not bypass WAFs, proxy restrictions or source access agreements.

## Backup and rollback

The new runtime state is `<AGUAYLUZ_DATA_HOME>/data/electricity/`, or
`data/electricity/` without a custom data home. It is ignored by Git. It contains
`ledger.sqlite3` and SHA-256-named `raw/` blobs. Source captures never overwrite
existing blobs. Candidate recommendations also use `reviews.sqlite3`; back up
and restore that ledger with its source database after quiescing writers. A Git
checkout is not a data backup. See `ADR-0002-candidate-review-ledger.md` for the
review role, immutable-history and recovery boundaries.
When monthly acquisition jobs are present, also preserve `acquisition.sqlite3`.
Restore all present ledgers and verified raw bytes together after quiescing
writers. Job recovery/cancellation semantics and remaining scheduling gaps are
documented in `ADR-0003-durable-monthly-acquisition.md`.

1. Stop acquisitions/imports and quiesce writers. Record the candidate commit and
   projection revision, raw blob hashes and receipt count.
2. Use SQLite's backup API to create a consistent database copy. Copy the raw
   directory into the same backup; independently verify every receipt's hash and
   byte count. Preserve existing water/GIS/other runtime stores separately.
3. Restore into a **new** directory, verify `EvidenceStore.snapshot()` and compare
   projection revision and measurement sets against the recorded backup.
4. For a development code rollback, start the preserved baseline checkout
   `3be8bb86df166b974e05b4880a0d19ce9a4d5e36` and retain the electricity directory.
   The baseline does not read the new plane; it must not delete it. Never reset a
   shared worktree or rewrite history to perform this rehearsal.
5. Restore service only after the applicable acceptance review. No production
   switch or data deletion is authorized by these development instructions.

`test_offline_rollback_rehearsal_restores_scientific_revision` exercises independent
DB/raw backup, further evidence append, and restoration to the exact prior
scientific revision, preserving the later live evidence. This is a local rehearsal;
production-equivalent restore and operational backup availability remain OPEN.

## Qualification artifacts

### Temporal registry

Electricity > Plant & generator registry exposes plant references and generator
source identities. Filters are literal and case sensitive; an effective instant
uses UTC and half-open source intervals. History retains every original assertion,
including assertions outside that instant. Source systems remain separate and
no capacity aggregation, operational status or crosswalk is inferred. All entries
are SOURCE_CANDIDATE / AUDIT_ONLY. The new read-only API is `/electricity/v1/registry`
and `/electricity/v1/registry/{entity_id}`. List continuation and every history
request require the exact scientific `revision`; a stale revision returns 409.
Unknown/repeated query parameters return 422. Missing or corrupted raw evidence
returns a redacted 503, not empty results. Exports contain the current page only.

The registry has no tables or scientific writes. Deactivate it by using the
preserved parent commit and retain all runtime data. For a restore rehearsal,
quiesce writers, back up the source database and raw bytes as above, then compare
registry source revision, structured entity IDs and every claim-history page in
the restored directory. `tests/test_electricity_registry.py` exercises this while
preserving later live appends. Source review, actual consumer acceptance and
production/device recovery remain open.

The baseline manifest and requirement ledger are committed with the code. Test
logs, browser captures, dependency audits, clean-checkout revalidation and the
release manifest live in the delivery evidence directory, bound to the exact
candidate SHA. Do not write a candidate's SHA into its own commit and pretend it
is self-certifying. Independent scientific/source/consumer review remains a
separate gate from automated clean-checkout replay.
