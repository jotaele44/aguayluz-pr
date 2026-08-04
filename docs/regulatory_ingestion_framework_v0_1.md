# Provider-Agnostic Regulatory Ingestion Framework v0.1

Status: design-only, disabled, additive

## Objective

Define one provenance-safe ingestion contract for public regulatory records from EPA, FDA, USGS, DRNA, PRASA/AAA, and PREQB without enabling live retrieval or treating a source record as proof that two facility identities are equivalent.

## Safety boundary

This package does not register schedulers, call external services, write production databases, expose a GUI control, or promote candidate links into canonical facility identity. Provider records remain immutable observations. Entity links remain proposed until an explicit adjudication state is recorded.

## Canonical records

| Record | Purpose |
|---|---|
| `RegulatoryEntityObservation` | Source-specific statement about an organization, establishment, facility, site, owner/operator, or regulated unit. |
| `RegulatoryPermitObservation` | Permit, registration, authorization, franchise, listing, or license as reported by one provider. |
| `RegulatoryInspectionObservation` | Inspection, sampling visit, audit, field visit, or compliance evaluation. |
| `RegulatoryEnforcementObservation` | Warning, violation, order, penalty, recall, corrective action, or closure action. |
| `RegulatorySourceReceipt` | Byte-level retrieval and provenance metadata. |
| `RegulatoryEntityLinkCandidate` | Non-authoritative proposal connecting a source record to an AguaLuz facility. |
| `RegulatoryEntityLinkDecision` | Human or governed adjudication of a candidate link. |

All observations require `provider`, `provider_record_id`, `observed_at`, `retrieved_at`, `source_receipt_id`, `evidence_tier`, and `freshness_state`.

## Provider adapter contract

Every adapter implements the same logical stages:

1. `discover(query, checkpoint)` returns source record locators only.
2. `fetch(locator)` returns raw bytes plus transport metadata.
3. `normalize(raw_record, receipt)` emits zero or more canonical observations.
4. `checkpoint()` returns resumable state with no embedded secrets.
5. `capabilities()` declares record families, pagination, authentication class, rate-limit policy, and public-export constraints.

Adapters must not perform entity promotion. They may emit identifiers and normalized candidate attributes, but linkage is delegated to the entity-resolution layer.

## Initial provider profiles

| Provider | Initial record families | Authority boundary |
|---|---|---|
| EPA | facilities, permits, inspections, enforcement, program identifiers | Environmental regulation; not authoritative for ownership or water withdrawal unless explicitly stated. |
| FDA | establishments, registrations/listings, inspections, recalls, warning letters | Product and establishment regulation; not an environmental permit authority. |
| USGS | monitoring locations, observations, site metadata | Scientific monitoring; not a permit or operator registry. |
| DRNA | well permits, franchises, extraction authorizations, closures, enforcement | Puerto Rico natural-resource authority; record-specific currency must be verified. |
| PRASA/AAA | utility assets, service relationships, notices, permits where published | Public water and wastewater utility; public records may not expose all operational infrastructure. |
| PREQB | legacy environmental permits, inspections, enforcement, facility identifiers | Historical/legacy environmental authority; supersession by later agencies must be preserved. |

## Provenance and receipts

A receipt binds each normalized record to the retrieved representation using SHA-256, byte count, media type, retrieval timestamp, request locator, HTTP status when applicable, and optional response validators. Secrets, authorization headers, session cookies, and private tokens are prohibited.

A normalized observation stores the receipt ID and a deterministic `normalization_version`. Reprocessing the same raw bytes with a new normalizer creates a new observation version; it does not overwrite the prior interpretation.

## Freshness model

`freshness_state` is one of:

- `current`: provider explicitly indicates the record is active and the validity window has not expired.
- `historical`: record is explicitly historical, closed, superseded, archived, or outside its validity window.
- `stale`: expected refresh interval has elapsed without confirmation.
- `unknown`: no defensible validity or refresh rule exists.
- `conflicting`: provider records disagree about current state.

Freshness is computed independently from evidence tier. A T1 record can be stale; a recent T4 report can remain unverified.

## Entity resolution

### Candidate generation

Candidate links may be generated from exact identifiers, normalized names, addresses, parcel identifiers, coordinates, owner/operator relationships, and provider-specific IDs.

### Evidence classes

| Class | Examples | Default consequence |
|---|---|---|
| Hard identifier | exact FEI, EPA ID, permit number, DRNA franchise number, canonical parcel ID | Candidate may reach `strong`, but still requires contradiction checks. |
| Strong composite | exact normalized address plus compatible name and municipality | Candidate only. |
| Spatial composite | point within a bounded facility polygon plus compatible name/operator | Candidate only. |
| Weak lexical | similar name, municipality only, shared parent company | Never auto-promote. |

### Required contradiction checks

Before approval, evaluate incompatible municipalities, distant coordinates, mutually exclusive parcel identities, non-overlapping operating dates, conflicting legal entities, duplicate provider IDs assigned to different sites, and source records explicitly describing separate facilities.

### Decision states

- `proposed`
- `needs_review`
- `approved`
- `rejected`
- `superseded`
- `conflicted`

Only `approved` links may be consumed as canonical crosswalk edges. Approval must record actor, timestamp, rationale, evidence references, and the exact candidate version.

## Export policy

Raw receipts and source observations are preserved. Public export excludes credentials, restricted contact details, non-public coordinates, and provider payload fields not approved for redistribution. A public export must distinguish source assertions from AguaLuz adjudications.

## Runtime activation gates

Live activation requires a separate change containing:

1. provider-specific legal/terms review;
2. bounded rate limits and retries;
3. checkpoint and replay tests;
4. negative fixtures for malformed, stale, duplicate, conflicting, and retracted records;
5. persistence migration and rollback plan;
6. GUI capability registration for user-visible workflows;
7. end-to-end provenance display;
8. security review confirming no secrets enter receipts or logs.
