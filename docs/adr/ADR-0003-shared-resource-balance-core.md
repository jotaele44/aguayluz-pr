# ADR-0003: Shared Resource Balance Core

- **Status:** Proposed
- **Date:** 2026-08-04
- **Pinned base:** `17c843595b5cdfbcef4e5f7b1ac6c662092e335d`

## Context

AguaYLuz already owns water and electrical infrastructure records, observations, incidents, alerts, diagnostic GUI surfaces, and federation exports. Building a second independent loss system would duplicate identity, provenance, freshness, uncertainty, topology, review, and investigation controls.

## Decision

Introduce an additive `resource-balance/v0.1` contract bundle and a design-only reference implementation. Share accounting mechanics across water and electricity while keeping domain physics separate. Preserve existing records through compatibility wrappers. Legacy readings are not balance-eligible until direction, interval, topology, and uncertainty are explicit.

## Safety boundary

A residual is an accounting discrepancy. The core cannot assert theft, fraud, illegal diversion, unauthorized use, or an exact failure location. Attribution defaults to unresolved and requires corroboration plus human adjudication.

## Consequences

- Existing runtime behavior remains unchanged.
- Open PRs #101, #116, and #118 remain independent and require later overlap adjudication.
- API, GUI, federation export, alerts, notifications, scheduling, data migration, and deprecation are deferred.
- Runtime promotion requires regression equivalence, full CI, rollback evidence, and a separate approval.
