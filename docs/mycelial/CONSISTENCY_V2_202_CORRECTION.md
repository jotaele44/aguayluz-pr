# Mycelial consistency correction 2.0.2

This revision addresses S1/S2 from exact-head review `5187694410` of
`2371312ff96bbdbaeef4b671fa909ef81f4f5a97`, following the user's `go` directive.
It preserves that reviewed commit and its failing evidence. Record schemas remain
2.0.0 and byte-identical. There is no migration, admission service, source fetch,
field event, runtime, prediction, ready transition or merge authorization.

### S1: timezone lookup is a bounded resource-access boundary

Before `ZoneInfo` is called, keys must be nonempty ASCII letters/digits/underscore/
plus/minus components separated by single slashes. The implementation limit is
255 characters overall and 64 per component. These are operational input limits,
not proof that a syntactically valid key is a real timezone. No normalization,
case folding, path traversal, absolute path or silent UTC fallback is performed.

Expected lookup failures return constant reason codes:

- `TIMEZONE_KEY_INVALID`: key shape or length does not meet these limits;
- `UNRECOGNIZED_TIMEZONE`: no matching zone was available; a missing database is
  not distinguished from an unknown key without independent evidence;
- `TIMEZONE_DATA_ACCESS_FAILURE`: `OSError`, including directory, permission and
  filename errors, encountered within the timezone resource loader;
- `TIMEZONE_DATA_INVALID`: invalid/truncated data reported as `ValueError` or
  `EOFError` by the loader.

Only the lookup boundary catches these expected failures; there is no blanket
exception-to-success handler. Conversion overflow retains its earlier explicit
rejection. Error results do not echo keys, filesystem paths or exception details.
The module neither enumerates the host filesystem nor resets the timezone cache.
System and tzdata fallback behavior is documented by Python:
https://docs.python.org/3.13/library/zoneinfo.html

### S2: archived definition edges are not active-use edges

The reference helper now distinguishes three roles in diagnostic candidate output:
`active_use`, `historical_predecessor`, and `historical_definition`. The third role
is derived internally only when the requesting record explicitly has
`review_state=superseded` and the edge would otherwise be a definition/active-use
reference. It is not a caller-supplied flag and is not inherited by current rows.

Consequently an archived plan may be checked against a superseded substrate,
site or target definition without reactivating any of them. The same contextual
rule applies to other archived definition chains, including archived surveys and
observations. A superseded target of a historical-definition edge adds
`HISTORICAL_DEFINITION_NOT_ACTIVE`; a predecessor edge keeps
`HISTORICAL_PREDECESSOR_NOT_ACTIVE`. The archive record itself still has
`REVIEW_STATE_NOT_ELIGIBLE`. Every authority flag remains false.

Current requesters still fail direct use of a superseded dependency. A historical
label does not suppress malformed rows, tied identities, missing references,
rejected/retired dependencies, hash mismatches, chronology errors or cycles.
All those checks and downstream failure propagation continue to execute.

This checks the internally consistent assertions supplied in the bundle. It does
not authenticate review status, establish immutable historical snapshots, select
an effective winner among competing commitments or modify committed definitions.
Real existing hashes that do not match supplied records still fail. No historical
status is rewritten and no hash is recomputed by the checker to manufacture a
match. Rehashing in synthetic fixture builders is test construction only.

### Regression preservation and certification limits

The 23 review cases are carried forward without changes to their eleven test
function ASTs; only module/fixture loading paths are adapted. The previous 140
cases retain their logic: only the expected implementation-version string moves
from 2.0.1 to 2.0.2. The record-version/hash assertions remain unchanged. Sixty-two
additional cases cover invalid-key pre-I/O rejection, injected expected loader
failures, known aliases, complete archived chains, current-use rejection, hash
mismatches, malformed/ambiguous predecessors, chronology, cycles, non-mutation,
non-admission and order independence. This gives 140 + 23 + 62 = 225 distinct
scoped cases; actual execution receipts are outside this source document.

No failed baseline evidence is overwritten. Tests involving injected I/O failures
are explicitly simulations; actual directory/overlong-key reproduction remains
in the carried review cases. Successful local tests do not certify Python
3.10/3.12, complete repository integration, lint, security, coverage or builds.
The earlier OPEN design questions remain separate. No reviewer or biological
approval is invented by this correction.
