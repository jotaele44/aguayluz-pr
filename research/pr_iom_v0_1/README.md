# PR-IOM v0.1 — Puerto Rico Infrastructure Obsolescence Master, baseline package

PR-IOM asks which obsolete components in Puerto Rico's electricity and water
infrastructure can be replaced, refurbished, remanufactured or retrofitted, instead of
treating obsolescence as irreversible. Execution vector: `PR-IOM-001`.

This package is the evidence baseline captured on 2026-11-25. It classifies nothing as
obsolete. The narrative, contradictions, confidence and blind spots are in
[`docs/PR_IOM_OBSOLESCENCE_LEDGER_2026-11-25.md`](../../docs/PR_IOM_OBSOLESCENCE_LEDGER_2026-11-25.md).

## Files

| File | What it holds |
|---|---|
| `taxonomy.json` | Nine infrastructure classes, eight status codes (`O0`–`O6` plus scarcity), strategy codes `R1`–`R7`, six evaluation criteria |
| `execution_plan.json` | The 30 steps of `PR-IOM-001` in six phases, each with state, dependencies, evidence, exit criteria and blocker |
| `public_source_receipts.json` | 48 sources: URL, retrieval time, SHA-256 and size for stable files, evidence tier, what each supports, terminal state |
| `source_coverage_matrix.json` | The seven quantities the investigation wants, and how far public sources cover each |
| `asset_universe_baseline.json` | Counts of the asset rows already in this repository that components will bind to |
| `component_registry.json` | 15 candidate component records transcribed from one regulatory filing |

The record schema is `schemas/pr-iom/v0.1/component_record.schema.json`. The checks are in
`tests/test_pr_iom.py`.

## Reading rules

- **A record is a claim, not a finding.** Each registry record is an operator statement
  from a filing. Status stays `O0_UNVERIFIED` until the manufacturer is identified and its
  production status is shown from a primary record. The schema refuses any other status
  without a verified manufacturer.
- **End of life is not obsolescence.** A worn-out motor may still be in production.
  Fourteen of the fifteen records say "end of life"; one says "obsolete".
- **A part being needed is not a part being unavailable.** The outage workbooks record that
  a part was needed, not whether it was in stock or still made.
- **Vendor material is capability reference only** (tier T4) and never supports a record.
- **Raw documents are not committed.** Only receipts are. Re-fetch from the URL and compare
  the SHA-256.

## Disclosure

Everything here comes from public regulator dockets and published reports, at plant and
unit level (`public_approximate`). Records obtained from an operator under restriction
must be marked `operator_restricted`; the schema then prevents them from being accepted
for publication. Public output is aggregate findings and rehabilitation opportunities.

## Regenerating

The package was assembled by hand-run analysis, not by a committed script. To extend it,
add sources and records to the JSON files and run `python -m pytest -q tests/test_pr_iom.py`.
