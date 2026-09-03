# ADR-0003: Additive Integrated Water-Movement Ledger

- Status: Proposed
- Date: 2026-08-04
- Decision scope: Design only
- Base: `main@17c843595b5cdfbcef4e5f7b1ac6c662092e335d`

## Context

AguaYLuz already contains static utility assets, routine monitoring readings, hydrologic and environmental ingestors, alerts, source manifests, review queues, append-only water-disruption incidents, GUI surfaces, and federation exports. These components were built for distinct purposes and do not presently form a single volumetric accounting system.

Adding a separate unaccounted-water module without reconciliation would duplicate asset identity, freshness, provenance, quality, incident, and export logic. Replacing the existing schemas would create migration and regression risk.

## Decision

Adopt an **additive canonical water-movement ledger** as the analytical compatibility layer.

1. Existing source schemas and records remain authoritative in their current roles.
2. Existing records are projected into versioned canonical records with full lineage.
3. Assets and hydraulic flow edges are separate concepts.
4. Observations, derived ledger entries, balance assessments, and causal interpretations are separate records.
5. Balances are nested by watershed, reservoir, groundwater, treatment, transmission, and distribution boundaries.
6. Uncertainty, freshness, quality, and lineage are first-class objects.
7. A residual is not proof of physical loss, illegal withdrawal, theft, diversion, or operator misconduct.
8. Balance findings cannot bypass the existing alert and incident validation systems.
9. No balance product is exported or publicly exposed until separate privacy and federation ballots approve it.

## Consequences

### Positive

- Preserves proven source and incident contracts.
- Enables system-wide and subsystem mass balance without destructive migration.
- Supports localization to the first failed boundary.
- Makes missing, stale, contradictory, and unsynchronized terms explicit.
- Prevents provider coverage from being mistaken for current observations.
- Provides a bounded path for later reservoir, groundwater, plant, transmission, and distribution pilots.

### Negative

- Requires explicit mappings and may expose substantial identity and unit debt.
- Some balances will remain underdetermined until operator telemetry becomes available.
- Dual-read and shadow-projection phases increase implementation work.
- Multiple records may represent the same real-world quantity until source-equivalence adjudication is complete.

## Rejected alternatives

### Independent unaccounted-water service

Rejected because it would duplicate assets, provenance, freshness, and alert logic and would increase contradiction risk.

### Full rewrite of existing monitoring schemas

Rejected because current data, APIs, tests, GUI, incidents, and federation contracts depend on them.

### Treat the asset dependency graph as hydraulic topology

Rejected because dependency, proximity, power, and service relationships do not prove water flow direction or quantity.

### Treat model residual as measured loss

Rejected because residuals can arise from measurement uncertainty, timing mismatch, unit errors, missing records, storage-curve errors, and incomplete process models.

## Implementation hold

This ADR remains proposed until the design PR is reviewed. No runtime implementation, data migration, GUI activation, scheduler change, alert promotion, incident promotion, or federation export is authorized by this decision record.