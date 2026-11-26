# Hydro Intelligence V2 — Financial authority boundary (candidate)

Status: DESIGN_CANDIDATE / NOT ACTIVATED. This document defines an ownership and acceptance boundary, not an operating financial feed or certification receipt.

## Authority

* MoneySweep-PR alone acquires, normalizes, deduplicates, and governs financial awards, contracts, obligations, outlays, disbursements, and expenditures.
* AguaYLuz-PR owns hydroelectric asset, generator, hydrology, generation, outage, rehabilitation, and recovery evidence. It consumes read-only MoneySweep financial projections only when an authoritative contract and verified receipts exist.
* Spiderweb-PR governs spatial source/feature evidence; TheHub-PR coordinates cross-repository contract identities, pins, and LOCKSTEP. Existing MoneySweep federation export passes through the Spiderweb query-hub consumer; do not introduce an undocumented direct feed or duplicate governance.
* Mucaro-AI may produce separately labeled models/estimates, not authoritative financial observations.

## Consumption contract — required before activation

A financial-to-hydro linkage must carry `financial_record_id`, `money_sweep_source_revision`, `source_receipt_sha256`, `financial_record_type`, `financial_amount`, `currency`, `amount_semantics`, `as_of_date`, `hydro_entity_id`, `link_evidence_refs`, `identity_verification_status`, and `provenance_state`. The record must satisfy `schemas/hydro_financial_link.v1.schema.json`.

Consumption is fail-closed unless producer export contract version, package digest/receipts, consumer pin and mapping rules are verified on the exact head. The existing MoneySweep v1.2.0 export is documented for Spiderweb query-hub; compatibility with this proposed projection is UNVERIFIED until a consumer adapter and bilateral fixture are implemented and tested.

No joins by name, proximity, cost similarity or award amount alone. One award may relate to multiple projects; preserve cardinality and allocation basis, never sum full amounts across unverified relationships. `obligated`, `disbursed`, `expended`, `awarded` and `estimated` are distinct semantics. Null or disputed links remain unresolved.

## Hydro analyses

AguaYLuz may compute cost per *verified* recoverable MW, cost per modeled MWh, funding gaps, and intervention scenarios using qualified MoneySweep projections. Every result must carry original financial identity/receipt and AguaYLuz operational/head assumptions; distinguish FACT from COMPUTED, BINDING, INFERENCE and UNKNOWN. Do not label a forecast as actual generation or a financial obligation as actual expenditure.

## Acceptance gates

1. Freeze source and destination exact commits, contract version, manifests and SHA-256.
2. Audit overlapping current modules; no independent AguaYLuz financial ledger or financial scraper introduced.
3. Validate positive and negative schema cases, missing producer receipts, stale consumer pins, currency/amount mismatches, unverified link, duplicate allocation, and wrong financial semantic.
4. Verify fixture interoperability with MoneySweep producer and existing Spiderweb consumer, and explicitly reconcile TheHub receipts.
5. Preserve preexisting hydro master, operation status, financial records and source bytes; no automatic identity promotion.
6. Run exact-head CI/security and downstream replay; request required reviews and qualify before merge.
7. Mark finance-hydro integration OPEN and production certification WITHHELD until all above gates PASS.

## Initial bounded execution

Start with six PNNL generation-reporting hydro plants as candidate asset identities, but never infer financial linkage from their names. Separate historical PNNL generation observations from 2025–2026 current operational evidence. Maintain PNNL as secondary historical evidence, not a replacement for source-native EIA/LUMA/PREB material.

## Current state

This PR is contract scaffolding only. No source-byte imports, runtime feed, MWh reconciliation, linkage assertions, tests, merge, deployment or LOCKSTEP certification are claimed.
