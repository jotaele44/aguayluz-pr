# Ionosphere RC1 — acquisition evidence and gate repair

State: AUDIT_ONLY. RC0 and its passed artifacts remain preserved at published commit
aa2970e39a6af9325316bfaf463172917fddd430 (same tree as local 7d4ab373).
Its SHA256 file describes that historical tree, not the changed RC1 working tree.

## Findings

- GitHub default browser job 120541165756 at RC0 completed 31/31 browser tests,
  plus 4/4 CaveKarstPage unit tests. This supersedes the RC0 local missing-browser
  blocker for DEFAULT behavior only. Enabled-preview verification was not included.
- RC0 validate run 39990575525 stopped at Python test formatting (E701/E702/I001).
  Formatting has been repaired without modifying assertions or weakening the gate.
- Local NOAA acquisition again returned HTTP 403. Frozen bytes and retrieval UTC
  are in docs/ionosphere_evidence_rc1/local-acquisition, including the response hash and
  measurement_count=null. This is a failed request, not an empty observation set.
- New development-only CI capture preserves bytes and receipts on both outcomes.
  ACQUIRED_UNVERIFIED means raw FeatureCollection schema inventory only; geometry,
  null-value interpretation, coverage, units and operational quality remain separate.
  Capture fails its CI gate on HTTP or schema failure, while always saving evidence.
- Added an explicit enabled-preview browser test step after the default GUI gate.
  No preview flag is enabled in production by this workflow.

## Producer binding

PITIRRE remains repository ID 1261399537, currently named jotaele44/skywatcher-pr.
Read source tree: 770517f42fdd8aa90b89faebf3069795e564913b.
Its frozen observation schema Git blob is fa83d3bad56fcdf251f5822b0e58fdb8df2b4943;
local Git blob computation matches. See docs/ionosphere_evidence_rc1/binding.json.
The schema only permits airspace_observation, maritime_baseline, and
spacetrack_normalized_gp as adapter legacy_contract values. It does not yet accept
an ionosphere contract. Identity binding is supported; persisted integration is
BLOCKED pending a versioned schema/adapter change. Do not relabel TEC as one of
those unrelated contracts to pass validation. The manifest also declares
NON_PRODUCTION_DIAGNOSTIC and ready_for_hub_live_execution=false.

## ROTI acquisition frontier

Authoritative dataset metadata establishes candidate PR GNSS inputs, not processed
ROTI availability, suitable sampling, or current receiver health:

| Station | Dataset DOI | Source-reported geography | Remaining gate |
|---|---|---|---|
| HUPR | 10.7283/T5S46QQQ | University of Puerto Rico Humacao Campus; 18.1488, -65.8386 | Retrieve observables, inspect cadence and signals, validate cycle-slip/elevation handling |
| GEOL | 10.7283/T5BR8QHZ | Geology Building UPRM; 18.2113, -67.1395 | Same gates; historical metadata does not prove present availability |

Metadata pages: https://www.unavco.org/data/doi/10.7283/T5S46QQQ and
https://www.unavco.org/data/doi/10.7283/T5BR8QHZ . These are discovery candidates,
not substituted ROTI feeds. No coordinates were inferred from names or proximity.

## Fixed denominator assessment

ION-01 PASS retained. ION-02 PROVISIONAL pending enabled GUI evidence.
ION-03 BLOCKED pending real capture; ION-04 OPEN; ION-05 UNRESOLVED.
ION-06 identity audit PASS but contract compatibility BLOCKED; whole gate BLOCKED.
ION-07 OPEN; ION-08 OPEN; ION-09 and ION-10 BLOCKED.
No exact-release certification, deployment, operational monitoring or skill promotion.
Plan score 95/100; hardening design 96/100 (judgment scores, not completion percentages).

Local validation before publication: 16 Python tests and 25 subtests PASS; full
repository ruff check PASS; GUI inventory parity PASS with no baseline regeneration.
Exact successor CI is pending; RC0 CI success cannot certify a successor commit.
