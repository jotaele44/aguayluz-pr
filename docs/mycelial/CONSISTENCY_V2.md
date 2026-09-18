# Mycelial consistency contracts v2.0.0

State: DRAFT / INTERNAL RESEARCH VALIDATION ONLY. Not an admission service.

## Scope and lineage

This independent revision starts at main `bb0e18abf4d5d13002421f170a50654bf11a223b`.
PR #238 at `7f7fa5f9826604c2d47e04267bb6cd6c76fc97fb` and PR #253 at
`d8ac42470c9e7f3dc289f049c841434b2277c23d` remain unchanged audit baselines.
No unmerged branch is used as the new branch's parent.

The approved task is a versioned implementation of the prior read-only checker,
not source ingestion, field approval, production, calibration or prediction.
ADR-0002 remains controlling. No previous admission restriction is superseded.

The saved audit archive reused as input has SHA-256
`c4e1b4acea20b1a2bfbf3051101d81fe30f29096dce18445996bc2948abd0e43`.
All 36 member paths, sizes and SHA-256 values were checked against its supplied
manifest before reuse. This is an audit archive, not a biological export.

## New bounded implementation

`research/mycelial/consistency_v2.py` is import-only, read-only infrastructure.
It has no CLI, route, application object, network request, persistence, scheduler,
notification or production import. It is not a normal end-user workflow and
therefore does not add a GUI capability. The v1 files and GUI parity baseline
are not edited. Review of the applicable repository parity gates remains required.

`check_bytes` is the intended untrusted-input entrypoint. It enforces a 2 MiB
limit, unique JSON keys, finite numbers, valid UTF-8 and bounded nesting/nodes.
Strings are not normalized or rewritten. Parsed dictionaries cannot prove their
prior raw serialization, so direct dictionary checks have a narrower scope.

All results keep `record_admitted`, `field_authorized`,
`public_export_authorized` and `model_eligible` false. No caller may use a
PASS_CHECKED_CONSTRAINTS result as an ingest or permission token.

The caller retains rejected original bytes and receipts only where permitted.
This module never stores or destroys originals and returns reason codes/row
indices, not input locators, source text or entity IDs. It is NOT a complete
free-text/media deidentification system. Public export remains unapproved.

## Versioned contracts and semantics

The seven contracts are in `schemas/mycelial-consistency/v2/contracts.schema.json`:
site, target, survey, observation, receipt, substrate and preschedule. All records
require schema_version 2.0.0. The code binds the exact schema bytes by SHA-256;
changing schemas requires updating the code binding and rerunning tests.

- Verified permission claims require a nonblank reference, but the reference's
  authenticity, current validity and scope are not checked here.
- Withheld locations require null municipality/generalized-reference fields and
  coherent precision. Exact coordinate fields are not admitted.
- Observer cardinality, paired/ordered timestamps and person-time capacity are
  checked. Alternate timestamp offsets representing the same instant are preserved
  and flagged for review. An IANA timezone database must be available; a missing
  database or unknown zone fails closed, including on Windows.
- Counts distinguish exact, range, unknown and minimum estimate. In v2 only,
  minimum_estimate uses a positive lower_bound with null value/upper_bound.
  This is a new explicit representation, not a reinterpretation of v1 records.
- Repeated measurement IDs and contradictory capture/hash/binding states fail.
  A syntactically valid payload hash still does not prove actual payload bytes.
- References resolve within explicit namespaces. Every matching row is retained,
  including malformed rows sharing an ID. Ties are blocked, never resolved by
  arrival order. Even identical duplicate rows remain held; replay admission is
  outside this checker. Dependency failures and cycles propagate.

## Substrate and preschedule evidence

A substrate unit is a sampling object, not a fungal individual or network.
It has its own ID, site reference, registration time, definition and identity
reference. These fields are assertions requiring independent review.

A preschedule commitment records a manifest, reported commitment time, evidence
reference, exact logical manifest digest, and optional predecessor. Manifest
entries identify a planned survey/site/target/substrate scope and bind the
supplied site, target and substrate definitions by logical hashes.

Serialization `aguayluz.sorted-json-utf8/v1` is Python JSON with sorted keys,
compact separators, ensure_ascii=False, allow_nan=False, UTF-8, and no Unicode
normalization. This is NOT RFC 8785 and NOT an original-byte hash. Other
serializations require their own identifier and must not be compared as equal.

The checker verifies the manifest digest, definition bindings, unique entries,
reported commitment before both planned and actual visit times, substrate/site
binding, and supersession ordering/cycles. It does not authenticate the external
clock or evidence reference: PRESCHEDULE_AUTHORITY_NOT_VERIFIED remains a hold.
An asserted timestamp alone never proves actual precommitment.

Survey substrate_unit_ids mean actually examined units. Completed visits must
match the declared planned unit set. Incomplete positive observations may be
retained; they do not become completed negatives. Missed visits have no examined
units and cannot have fruiting objects. Changed effort is preserved and flagged,
not overwritten to match the planned effort. A completed visit with no detection
is non-detection under recorded effort, never ecological absence.

## Compatibility and migration

There is no automatic migration. V1 inputs fail the v2 version gate and remain
preserved separately. An explicit later mapping must supply real substrate and
preschedule references; it may not invent missing commitments or timestamps.

At the record-family-role level only:
- INTERSECTION: site, target, survey, observation, receipt (5).
- A_ONLY (prior role set): none (0).
- B_ONLY (v2 role set): substrate, preschedule (2).
- UNION: all seven roles (7).
- SYMMETRIC_DIFFERENCE: substrate, preschedule (2).
These are role sets, not byte/schema/logical-record or biological equivalence.
The five shared roles have changed constraints; all v2 contract bytes are new.

No DDL, migration script, canonical write path, fieldwork permission, actual
biological record, prediction or inference is introduced.

## Execution and certification

Run the isolated developer suite:

    python -m pytest -q tests/test_mycelial_consistency_v2.py

The suite loads the module directly to avoid importing unrelated production
application code. This makes its scope explicit; it does not establish complete
application import, GUI, repository-wide conftest, packaging or deployment parity.
It uses existing jsonschema/pytest dependencies and a system IANA timezone database.
Required repository checks and Python/platform matrix remain separate obligations.
Do not lower coverage, disable checks or mark the PR ready/merged from this result.

The independent final source/test/schema hash manifest and test logs accompany the
execution artifact and PR discussion. No report committed inside its own revision
claims to know its future commit hash.

## Remaining external gates

Source rights and bytes; media and taxonomic evidence; access/permission review;
independent commitment evidence; field execution; duplicate/identity adjudication;
canonical admission; software-wide certification; calibration and production.
None is proven by successful structural/semantic validation.


## Correction-only implementation 2.0.1

The record contracts remain **2.0.0** with unchanged schema bytes and logical
serialization. The Python implementation is identified separately as **2.0.1**.
This is a correction of the four findings in review `5187373378` against commit
`397a7c42c36195f1bfaaa06b3fa5939bdbf76bb0`, authorized by the user's subsequent
"Proceed". That reviewed commit and its failure evidence remain preserved.
No field, ingestion, model, public-output, ready-transition or merge authority is
added. The PR remains draft pending exact-revision review and repository gates.

1. **Untrusted integer arithmetic:** person-time capacity is evaluated only when
   observer cardinality agrees with the supplied pseudonym list. It uses that
   structurally bounded list length rather than coercing an arbitrary-size claimed
   observer count to a float. A mismatch still fails, and excessive effort still
   fails. No raw numeric value is changed or discarded.
2. **Temporal boundaries:** parsed timestamps must have a representable UTC
   instant. Conversion overflow for the declared IANA zone returns a constant
   `TIMESTAMP_ZONE_OUT_OF_RANGE` failure instead of escaping the entrypoint.
   Representable near-boundary dates remain supported. Invalid UTC-range values
   are rejected by the format check; neither case authenticates a real event.
3. **Offset components:** ASCII clock/offset components are range-checked before
   `datetime.fromisoformat`, including offset minutes 00--59 and hours 00--23.
   Parser normalization no longer grants validity to an offset such as +00:60.
   Original strings remain unchanged. This is not a claim of complete RFC 3339
   support: leap seconds remain unsupported, and existing datetime precision
   limits remain. See RFC 3339 section 5.6 and Python's datetime documentation:
   https://www.rfc-editor.org/rfc/rfc3339.html#section-5.6
   https://docs.python.org/3/library/datetime.html#datetime.datetime.astimezone
4. **Historical edge roles:** only the two internal supersession call sites use
   the historical-predecessor role. A structurally consistent `superseded`
   predecessor can be inspected, with `HISTORICAL_PREDECESSOR_NOT_ACTIVE` retained
   as a review hold. Direct active use of that same record remains rejected.
   Rejected/retired predecessors, ambiguous IDs, malformed rows, cycles, chronology
   conflicts and dependency failures retain their fail-closed treatment.

The additional test module preserves the ten review expectations (eight test
functions, one parameterized into three cases). Their assertion/function ASTs are
unchanged; only a self-contained fixture/import harness is supplied. Forty-four
additional cases exercise numeric and calendar boundaries, offset syntax,
unchanged valid offsets, dependency propagation, historical substrate references,
and active-use, duplicate, cycle, order and non-admission controls. The original
86-test file is unchanged. The total planned distinct correction check set is
86 + 10 + 44 = 140; actual results, commands, file hashes and execution windows are
reported outside this document in the review packet and PR discussion. Test code
or this documentation alone is not an execution certificate.

Full required Python/platform/security/build/coverage and repository integration
checks remain separate. No schema migration, DDL or production import is added.
The three open design observations about parallel commitments, lost-substrate
status, and partial versus complete detecting-survey bundles are not adjudicated
by this four-finding correction and remain outside its bounded PASS claim.
