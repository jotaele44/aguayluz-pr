# Temporal source registry

Status: accepted for isolated implementation; full release NOT CERTIFIED.

The native registry projects only immutable generator claims already admitted to
the electricity evidence store. It adds no scientific writes and no canonical
asset identity. A plant entry is explicitly a reference from generator source
plant IDs; it is not an independently verified plant record. Different source
systems remain separate even when their IDs, names or coordinates coincide.
Generator IDs retain literal strings, including `01` versus `1` and punctuation.
Entity IDs hash versioned structured tuples; complete claim IDs reuse the review
ledger contract. No inferred aliases, crosswalks or physical connectivity exist.

Intervals are half open: `[valid_from, valid_to)`. Missing end times remain open;
a later snapshot never silently closes earlier claims. A selected UTC instant
filters assertions, not actual operating status. Multiple active assertions are
retained. Overlapping disagreement on name, status or nameplate MW is UNRESOLVED;
no winner, capacity sum or zero-output interpretation is produced. Installed,
seasonal and available capacities cannot be substituted for source nameplate MW.

Versioned read-only list/detail contracts carry the scientific source revision.
Pagination and detail requests pin that revision and reject stale views with
409. Invalid, duplicate and unknown query arguments are rejected. Each bounded
page returns explicit counts and a continuation offset. Source corruption fails
closed; an empty store returns UNAVAILABLE without creating files. Source receipt
links, hashes, license, publication/retrieval dates and full claim history remain
inspectable and exportable. Filtering and selection are presentation state only.

The complete human workflow is native navigation → registry filters/pagination →
entity history and source receipts → exact evidence export. English/Spanish,
keyboard, narrow screen, integrity failure/retry and stale revision recovery are
acceptance requirements. Positive and negative fixtures cover source separation,
literal IDs, half-open boundaries, overlapping contradictions, equal assertions,
future/missing intervals, deterministic ordering/replay, all pagination pages,
independent SQL counts, API/schema compatibility, unauthorized writes and raw
hash corruption. Original workbook/source and independent scientific acceptance
remain separate blocked gates. The existing projection v1, producer exports,
review/acquisition ledgers and GUI ratchet baseline remain unchanged.

Rollback: deactivate the new read-only GUI/API with the previous commit. No
database migration or data deletion is required. Rehearse source/ledger backup
restoration and compare exact IDs, counts and content revisions. This bounded
rehearsal does not establish production recovery time or device acceptance.
