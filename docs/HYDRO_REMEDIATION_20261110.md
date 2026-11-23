# Hydro remediation and V01–V07 evidence reconciliation

Status: **PROVISIONAL / NOT CERTIFIED**. This evidence supplement does not
replace or relax `HYDRO_AUTONOMOUS_ACQUISITION.md`, the source registry,
coverage floor, or any existing CI/security/GUI gate. No operational scheduler,
source authorization, release, independent approval, or promotion is granted.

## Binding and CI denominator

- Repository: `jotaele44/aguayluz-pr`, draft PR #392.
- Inspected feature commit: `62e9704dc3c2838fffaf2c5132a66e27920c0700`.
- Historical 14/16 workflow result: `1c403389b19fbcd1d569bf39da11e4964326e653`.
- The later 16 successful workflow families are associated with `62e9704`;
  the separately emitted CodeQL findings check `128983260812` **FAILS**.
  Its two findings are the runner's potentially uninitialized `output` and
  the receipt writer's empty exception handler. A successful CodeQL analysis
  workflow does not override that failure. `live-smoke` is SKIPPED.
- Freeze jobs checked out synthetic merge `9011a06fe2710350a9407463e761f05dc9a83985`,
  whose parents are main `78e0c54518126a955750be5acdee4b39038539d1` and the
  feature commit above. Do not label these whole-tree exact-feature-head tests.

Historical PFAS run `42311863964`, job `128214985712`, closes as
**8 = 4 FROZEN + 3 BLOCKED_HTTP_403 + 1 UNEXPECTED_FAILURE**. The unexpected
failure was inability to connect to Salud document 9479. The permitted 403
population alone did not cause its exit failure. Historical Salud run
`42311863916`, job `128214985896`, failed with connection refusal; the earlier
reported 404 is a separate historical observation, not independently replayed here.

Later PFAS run `42562894800` closes as **8 = 5 frozen + 3 blocked + 0 unexpected**.
Later Salud run `42562894709` freezes 3/3 documents and accounts for
**15,550,611 = 15,532,246 excluded + 3,023 retained + 15,342 unresolved** EPA rows.
The unresolved reasons close as **15,342 = 1,172 invalid end dates + 14,170 missing
PWSID/violation ID**. Neither success establishes zero unresolved source residue.
The workflow/script contracts are unchanged between the historical and inspected
feature commits. The source outages need no speculative URL substitution.

The downloaded CI archives were independently verified byte-for-byte against
the upload logs, with CRC checks and full path/size/SHA-256 member inventories:

| Artifact | Members | SHA-256 |
| --- | ---: | --- |
| PFAS `13649694438` | 14 | `b8993e25439b107b8bd8e2a0aaee27428af4dad2f9b9b29e9b0a97758742aa32` |
| Salud `13650262323` | 9 | `38849b997a74408eb7e73780bb1d650eb2d2cf9101d616627b9b5679be48992b` |

These preserved artifacts are historical execution evidence, not new acquisition
or certification of their source contents. Reuse them instead of downloading the
mutable source URLs to repair a downstream validation failure.

## Narrow corrections

1. Reject unimplemented discovery adapters before network access. Use explicit
   `try/except/else` control flow so successful discovery and failed transport
   each produce a defined result; invalid null bytes fail closed.
2. Publish a fully written and fsynced source receipt with an atomic, no-clobber
   link. Validate a concurrent winner; preserve previously published raw bytes.
   This is tested publication behavior, not a power-loss durability guarantee.
3. Enforce the exact five registered source IDs, rejecting omission, addition,
   or same-count substitution. This is registry membership, not entity identity.
4. Reject ZIP member paths that collide after separator/dot normalization and
   case folding. Preserve the exact original path in accepted inventories.
5. Include the existing Hydro browser test in the required GUI test configuration,
   and assert the exact source IDs and disabled automatic-ingestion status.

Ten new Python regression cases failed before these changes; the focused suite
then passed 78 tests with no skipped workbook tests. Exact successor-commit test
receipts belong outside this document to avoid self-referential commit hashes.

## V01 requirement population and evidence limits

The original preflight's seven critical invariants are set A; its eleven added
adversarial threats are set B. At **literal requirement-label granularity**:
INTERSECTION = empty; A_ONLY = all 7 A labels; B_ONLY = all 11 B labels;
UNION = 18; SYMMETRIC_DIFFERENCE = 18. These labels have semantic overlap;
the arithmetic is a requirement inventory, not a proof of independent coverage.
The accompanying `hydro_v01_v07_evidence.json` preserves every label and its
evidence/disposition. No condition disappears because a related test passed.

V01 remains CONDITIONAL_GO / PROVISIONAL. Independent adversarial approval,
source-native pagination/JavaScript/redirector handling, production queue and
vault ownership, crash/power-loss recovery, and genuine live acquisition are
not established by these offline tests. The current runner's retry loop is
in-memory, and its filesystem vault is not an approved production deployment.

| Gate | Evidence assembled | Remaining acceptance residue |
| --- | --- | --- |
| V03 | Generic allowlisted-link discovery and source-scoped revision classifier tests | Source-native adapters, original index fixtures, pagination closure, link-less publications, independent completeness assessment |
| V04 | Bounded retry/quarantine tests | Durable queue implementation, production owner/storage binding, restart/lease/idempotency/recovery proof |
| V05 | Unsafe URL, private/mixed DNS, pinned-IP hostname, redirect and 403 regression tests | Real TLS/source-host binding, cross-domain authority review, independent adversarial approval |
| V06 | Original-byte hashes, revisions, no-clobber and interrupted receipt publication tests | Approved durable vault, power-loss/crash recovery, full race/symlink threat adjudication, source-native replay |
| V07 | Byte receipt checks, orphan/tamper tests, archive member hashes, revision classifier | Integrated durable manifestation ledger retaining every URL/time/attempt, ledger-to-vault conservation, source-native completeness |

The one-receipt-per-payload vault is not itself a complete manifestation ledger:
the same payload may appear at multiple URLs/times, while its first payload
receipt remains immutable. The runner's per-run evidence partially retains
observations; do not infer full durable-ledger closure from that primitive.

## Readiness and next gate

Execution-plan assessment: **92/100**; hardening-strategy assessment: **90/100**.
These are planning judgments, not completion percentages. Strengths are stable
commit binding, regression falsifiers, unchanged thresholds and frozen artifacts.
The deductions reflect unresolved deployment binding, live source-native
contracts, independent review, and hosted successor-head validation.

V00 historical scoped evidence is preserved. V02 code corrections remain
subject to successor-head CI. V03–V07 remain OPEN overall. V08–V17 are not
individually certified by this tranche; their full acceptance contracts and
downstream receipts remain required. A1/A2, merge, Release A, Hydro Master,
TheHub LOCKSTEP and reusable skill promotion remain WITHHELD/BLOCKED.

Candidate training lesson: count workflow families, job conclusions, security
findings and tested checkout SHAs separately; always reconcile freeze arithmetic.
This is an unpromoted review case, not a trained or certified reusable skill.
