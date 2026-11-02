# AguaYLuz Source Intelligence V1

Status: backend-qualified candidate; no new live source activation.

## Purpose

Unify AguaYLuz-governed source families under one denominator, monitoring,
provenance and health contract while preserving source-native semantics.

The control plane keeps four gates separate:

1. source-family coverage;
2. source acquisition and parsing;
3. runtime monitoring health;
4. domain certification.

Coverage Matrix structural readiness is not frontend authorization and is not source-universe certification.

## V1 denominator

The bounded V1 catalog declares 20 governed domains and the first permanent
source-family denominator spanning energy, water, hydrology, weather, coastal,
environment, recovery, regulatory, GIS and remote-sensing authorities.

A denominator change is a governed schema change. New primary authorities are
added explicitly; they are never inferred from count equality.

## Source lifecycle

DISCOVER -> FETCH -> FREEZE -> HASH -> SCHEMA -> PARSE -> NORMALIZE ->
IDENTITY CANDIDATES -> RECONCILIATION -> OBSERVATIONS -> API.

Adapters never directly promote canonical identity.

## Frontend authorization boundary

Frontend control-plane work may consume the V1 API when:

- every material Domain x Source cell in the frozen denominator is classified;
- unknown primary source families inside that frozen denominator are zero;
- structural readiness is at least 95;
- IDs, enums and provenance semantics are versioned;
- a reference adapter passes positive and negative regressions.

This does not authorize claims that every source has a live adapter or that
AGUAYLUZ_SOURCE_UNIVERSE_CERTIFIED has passed.

## Hard negative invariants

- HTTP 200 is not success by itself.
- Expected-nonzero source plus zero rows is a validation failure.
- HTML returned at an XLSX endpoint is a transport/content failure.
- Same locator plus different bytes is a new source manifestation.
- Name, normalized name, proximity, count equality and capacity equality do not
  prove canonical identity.
- Historical PASS evidence cannot certify a later source manifestation.
- Source registry presence does not fabricate runtime health.

## EIA-860M reference adapter

The offline-safe EIA-860M adapter proves:

- canonical monthly archive URL generation;
- media-type and XLSX magic-byte validation;
- ZIP-container member validation;
- deterministic workbook sheet-name fingerprinting;
- malformed/HTML negative behavior.

The reference adapter implements bounded preamble/header detection, Puerto Rico-specific Operating/Retired sheet selection, raw-string preservation, Puerto Rico hydro filtering, and exact Plant ID + Generator ID invariants. The frozen 2026-11-02 reference receipt records authoritative January/February 2026 bytes, verified source SHA-256 values, 20 operating PR hydro units, 98.1 MW, 19 OP + 1 SB, and a Jan→Feb identity vector of INTERSECTION=20, A_ONLY=0, B_ONLY=0, UNION=20, SYMMETRIC_DIFFERENCE=0.

## API V1

Read-only control-plane endpoints:

- GET /source-intelligence/summary
- GET /source-intelligence/domains
- GET /source-intelligence/sources
- GET /source-intelligence/coverage

Sources without a unified runtime receipt expose null runtime health instead of
a fabricated healthy state.

## Current authorization state

The V1 Coverage Matrix may reach structural readiness before the backend does. Source Intelligence now includes content-addressed immutable raw storage, immutable SourceManifestation receipts, source-health receipts, a production parser implementation, identity invariants, and readiness scoring. The V1 API contract is frozen in code and backend readiness is evidence-backed by the committed EIA reference receipt. Frontend authorization may become PASS only when the exact-head CI wave for the candidate is green. Domain certification and AGUAYLUZ_SOURCE_UNIVERSE_CERTIFIED remain fail-closed until domain-level evidence gates and TheHub LOCKSTEP are separately proven.
