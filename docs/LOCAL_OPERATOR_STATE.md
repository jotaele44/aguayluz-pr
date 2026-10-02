# Saved local operator changes

The diagnostic dashboard stores review decisions and asset/event edits in a local
SQLite database. A successful write response means the override and its audit row
committed together. Restarting the backend does not discard confirmed edits.

Open **System & Tools → Saved local changes** to inspect saved-record and audit
counts, the last saved timestamp, and storage failures. **Retry local storage
check** refreshes that status. A store that has never received a write is shown as
not initialized, not as proof that a write has succeeded.

Asset flags are available in the asset detail panel. Saved overrides are applied
to the diagnostic asset list, map properties, coverage/sector summaries, and
municipio summaries. Event detail has separate **Acknowledge** and **Mark resolved**
actions. Acknowledging an event does not resolve it; a confirmed resolution
removes its active indicator. Event list, related-event, detail, stream, and
printable-report reads use the saved local state.

These actions do not rewrite source JSONL or canonical Federation exports. Record
details distinguish saved local overrides from original values, including source
fields that were absent rather than null. Canonical promotion remains a separate
adjudicated workflow. Existing in-memory edits from an already running older
backend cannot be recovered automatically after that process exits.

## Integrity and recovery

- Mutations require one exact stable-ID match. Missing IDs return 404; duplicate
  IDs return 409. If a later source refresh introduces duplicate IDs, an existing
  override is marked unresolved rather than applied to an arbitrary row.
- Review requests include the fingerprint supplied with the displayed item.
  Stale requests return 409. Changed evidence for the same record reappears in the
  queue even if an earlier version was accepted or rejected.
- Unsupported fields, nulls, invalid enums, and missing review bindings return
  422 without saving partial edits. This intentionally replaces the previous
  silent ignoring of unsupported fields.
- SQLite transactions serialize concurrent edits. Disjoint patches are merged;
  an audit insertion failure rolls back the override. Concurrent edits to the
  same field follow transaction order, with both writes retained in the audit.
- Storage failures return 503. The System page reports the problem. Corrupt
  databases are preserved; they are never silently replaced with an empty store.
  Stop writers and preserve the database before operator-led recovery.

The default path is `.aguayluz/operator_state.sqlite` under the repository, or
under `AGUAYLUZ_DATA_HOME` when a workspace is configured. Administrators can set
`AGUAYLUZ_OPERATOR_STATE_PATH` to an explicit database path. Keep the database and
any active journal together when backing up; for a simple file copy, stop the
backend first. An exported HTML report is not a backup of this local state.

GUI parity runs use a fresh temporary operator database, so browser tests cannot
change the operator's saved state. Temporary databases remain test artifacts.
The existing review fixture still uses hash-checked teardown.

## Verification

`tests/test_operator_state.py` covers reopening, namespace isolation, concurrent
patches, atomic rollback, invalid inputs, and corruption preservation.
`tests/test_operator_state_api.py` covers both the shipped API projections and
fresh-process recovery, plus stale review bindings, auth, duplicates, and visible
storage failures. Browser regressions in `dashboard/tests/gui-parity.spec.mjs`
exercise saved review decisions, System status, reload, and separate event
acknowledgment/resolution through the GUI.
