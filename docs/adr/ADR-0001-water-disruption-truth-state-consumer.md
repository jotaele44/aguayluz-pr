# ADR-0001: Agua y Luz as water-disruption truth-state owner

- Status: Proposed
- Contract: `prii.water-disruption/v0.1`
- Producer: `centinelas-pr`
- Consumer: `aguayluz-pr`

## Decision

Agua y Luz accepts append-only evidence and candidate events from Centinelas, validates their water-domain meaning, and alone owns canonical incident identity and operational status. A Centinelas candidate can never directly create a confirmed outage.

## Validation gate

Every candidate is assigned one decision:

- `accepted_unverified`: relevant but not confirmed
- `needs_review`: ambiguous location, infrastructure, freshness, or service effect
- `rejected`: not a public water-distribution incident
- `corroborated`: supported by independent evidence but not necessarily official
- `confirmed`: supported by an authoritative source or an approved corroboration policy

Confirmation requires either a T1/T2 authority whose scope covers the claim, or at least two independent sources plus explicit reviewer approval. Confidence score alone is never sufficient.

## Canonical incident lifecycle

`reported -> acknowledged -> confirmed -> repair_planned -> repair_in_progress -> partial_restoration -> restored -> closed`

Side states are `unverified`, `disputed`, `retracted`, and `cancelled`. Transitions are append-only lifecycle events. Invalid transitions fail closed. Restoration does not erase the outage; it closes the active service-impact interval.

## Canonical identity and deduplication

The incident dedup key uses normalized municipality/locality, infrastructure asset when resolved, service effect, cause family, and overlapping time interval. Candidate dedup keys are hints only. Agua y Luz may merge or split candidate groups while retaining every source candidate and evidence edge.

## Provenance

Every incident claim and lifecycle event references the candidate IDs, evidence IDs, validator/reviewer identity or policy version, decision timestamp, and payload hashes that support it. Derived GIS geometries retain method and source references.

## Retractions and corrections

A retraction creates a lifecycle/provenance event. It never deletes evidence. Agua y Luz recalculates the supported truth state, marks disputed or retracted incidents, and propagates corrections to alerts, maps, exports, and downstream federation consumers.

## Service impact

Canonical incidents may carry affected municipalities, barrios, sectors, roads, facilities, estimated customers, impact geometry, start/end times, and uncertainty. Unknown scope remains explicit; it must not be replaced with a fabricated polygon or customer estimate.

## API and GUI parity

The implementation phase must expose intake health, validation queue, evidence comparison, incident lifecycle, merge/split, restoration, retraction, map impact, and audit history through discoverable GUI workflows. Normal operation may not require terminal commands or hidden routes.

## Consequences

- Reporting noise cannot corrupt the operational incident ledger.
- Official, corroborated, disputed, and unverified states remain distinguishable.
- Restoration and correction history remains auditable.
- Existing sensor-alert operations remain separate but may correlate with canonical service incidents through explicit evidence links.
