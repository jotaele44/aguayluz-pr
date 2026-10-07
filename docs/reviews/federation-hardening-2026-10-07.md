# Federation code review — 2026-10-07

Review base: `71684f38a251f90af5c5510d9c2a36dd6f99f982`.

Scope: repository API and data boundaries, federation metadata, existing regression tests, GUI capability gates, and shared infrastructure where applicable. This is a targeted review with automated validation, not a claim that every possible defect has been eliminated.

## Changes

- **P1:** A later candidate matching an incident dedup key lost its candidate/evidence provenance and could not propagate retraction. Append a revised incident manifestation retaining unique candidate/evidence links, preserve historical records, and deduplicate affected incident IDs.
- **P2:** The existing Salud/SDWIS source-freeze infrastructure was absent from GUI capability classification. Bind it to the existing internal ingestion capability without changing the parity baseline.

## Validation

Validation results are recorded in the pull request description. Regression cases include invalid inputs and preservation of normal behavior. GUI parity baselines were not regenerated.

The review uses isolated local checkouts and synthetic regression fixtures. Existing frozen-source receipts retain their original scope and date; they do not establish live source freshness. Shared-package consumer pins remain immutable until a separate release/pin update.
