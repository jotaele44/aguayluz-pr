# Hydro Autonomous Acquisition — V00–V02 bounded preflight

This document establishes **design and contract gates only**, not operational
source acquisition or certification. PR #392 remains draft and unmerged.

## V00 frozen inputs

- Hydro feature baseline: `f68616d3a1f3041c331ae80086cfa2cc5db5ee0b`.
- Inspected main: `40d3ab165797df4e1234b808ab2c180cf9fc366b`.
- Historical baseline: 16/16 GitHub workflow families successful at the feature SHA.
- Source registry: `config/hydro_intelligence_sources.v1.json`.
- Snapshot status: main has advanced; exact integration requires a new verified
  full-tree comparison and full CI at a successor head.

## V01 independent requirements preflight

Critical invariants: original-byte integrity, no name-only binding, no
inference from missing source data, no silent NULL-to-zero, no unauthorized
promotion, no SSRF or unreviewed redirect, and no loss of publication revisions.
All are mandatory; any unresolved critical failure blocks release.

A separate adversarial pass adds: repeated URL/new bytes; multiple URLs/same
bytes; link-less JavaScript/redirector publication; index pagination; failed
source HTTP; mixed private/public DNS; storage crash; ZIP member collision;
temporal source conflicts; stale branch approval; and live-scheduler persistence.

Both passes agree that source discovery does not certify acquisition. Their
union is the acceptance population, and all B-only threats above remain
mandatory open checkpoints until independently tested. No false completeness
claim is made about still-unacquired source manifestations.

## V02 source adapter classification

The bounded contract validator `contracts.validate_source_contract` checks
schema/version, five-source denominator, IDs, URLs, intervals, raw-byte
requirement and explicit adapter classification.

- EIA-860M XLSX, EIA-923 ZIP, and LUMA BPS PDF: discovery adapter **contract**
  exists, but live source compatibility and autonomous scheduling remain OPEN.
- PREPA/HydroCo regulatory filings and PR GIS containers: dedicated adapters
  **REQUIRED**. Do not mark them as download-ready based on registry inclusion.
- None of the five source families receives operational acquisition PASS from
  this validator. All remain candidate-only until source-native evidence passes.

## Next vectors / hard gates

V03: source-native discovery, version and pagination tests.
V04: durable queue with process-restart replay; no ephemeral-runner-only vault.
V05: security-hardened HTTPS and reviewed cross-domain source bindings.
V06–V07: immutable source and index manifestations, member hashes and exact
receipt-to-byte reconciliation.
A1: genuine independent live acquisition and reviewed production persistence.
V08–V17: candidate parsers, identity, temporal/units, UI, recovery, adversarial
verification, human review, merged-head replay and federation LOCKSTEP.

**Verdict:** V00 source/HEAD inspection PASS; V01 scoped coverage design
CONDITIONAL_GO; V02 validation candidate awaiting exact-head CI. A1/A2,
production merge and Hydro Master certification WITHHELD.
