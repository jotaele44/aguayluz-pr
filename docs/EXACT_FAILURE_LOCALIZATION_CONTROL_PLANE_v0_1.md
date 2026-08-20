# Exact Failure Localization Control Plane v0.1

## Status

Design-executable, shadow-only reference implementation. It does not operate water infrastructure, activate notifications, write to production incident state, or represent synthetic fixtures as Puerto Rico operational observations.

## Frozen implementation base

- Repository: `jotaele44/aguayluz-pr`
- Base: `main@17c843595b5cdfbcef4e5f7b1ac6c662092e335d`
- Mode: additive research core, versioned contracts, synthetic verification, draft PR

## Localization grades

| Grade | Meaning | Promotion authority |
|---|---|---|
| `L0` | Cause family only | Analytical inference |
| `L1` | Service system or service area | Analytical inference |
| `L2` | Pressure zone | Analytical inference |
| `L3` | Specific facility or bounded segment candidate | Maximum analytical inference |
| `L4` | Exact asset | Accepted, current, T1 authoritative exact-asset assertion |
| `L5` | Field-confirmed physical defect | Accepted, current, T1 authoritative field confirmation after L4 |

Confidence, residual magnitude, outage volume, proximity, or repeated reports cannot independently produce L4 or L5.

## Control-plane architecture

1. **Directed graph** — sources, intakes, treatment plants, transmission segments, tanks, pumps, valves, pressure zones, distribution segments, service areas, sensors, and power sources use stable asset IDs. Hydraulic and dependency edges remain distinct.
2. **Observation intake** — timestamped flow, pressure, level, storage, production, demand, state, outage, restoration, work-order, assertion, and field-confirmation records are payload-bound and append-only.
3. **Freshness adjudication** — rejected, invalid, future, and stale observations are excluded from the current analytical state and retained in explicit ledgers.
4. **Diagnostics** — the engine computes bounded mass-balance residuals, upstream/downstream pressure discontinuities, outage clusters, and competing hypotheses.
5. **Candidate generation** — each candidate records supporting evidence, contradictions, missing telemetry, confidence, bounded targets, and required field tests.
6. **Promotion events** — exactness is materialized from append-only L4/L5 promotion events; the original assessment is never rewritten.

## Hypothesis families

- hidden leak or main break;
- confirmed transmission-main break candidate;
- pump failure;
- power loss at pumping asset;
- valve misconfiguration or unexpected closure;
- tank depletion;
- treatment failure;
- source-water shortage;
- unresolved service-delivery failure;
- unknown when admissible evidence is insufficient.

A balance residual is a structural signal, not proof of leakage, diversion, unauthorized use, operator misconduct, or an exact defect.

## Evidence and contradiction controls

- `T1`: authoritative operator, regulator, instrument, work-order, or field record;
- `T2`: operationally useful but non-authoritative analysis or public secondary source;
- `T3`: eyewitness/community report;
- `T4`: secondary/open-source context.

Every candidate retains missing telemetry and contradictions. Restored-service evidence decreases a break candidate. Reported available power contradicts a power-loss hypothesis. Public/operator views preserve control-level disclosure boundaries.

## Public and operator views

Public output masks exact identifiers for pumps, valves, sensors, and power sources unless the asset is explicitly `public_exact`. Operator view is disabled by default and is read-only even when enabled. Neither view confers authorization to operate infrastructure.

## Append-only streams

- `graph_snapshots.jsonl`
- `observations.jsonl`
- `assessments.jsonl`
- `promotion_events.jsonl`

Idempotency keys are bound to payload hashes. Reuse with changed content fails closed.

## Verification corpus

The committed fixture is explicitly synthetic and covers:

- known main break;
- hidden leak candidate;
- pump failure;
- valve misconfiguration;
- tank depletion;
- power loss;
- multicausal shortage plus pump failure;
- unresolved outage;
- stale observation exclusion;
- L4 and L5 promotion gates;
- public redaction and disabled operator view;
- deterministic replay and append-only history.

## External activation gates

Operational localization requires provenance-bound PRASA/AAA topology, stable asset IDs, pressure-zone boundaries, current flow and pressure telemetry, tank levels, pump and valve states, treatment production, source availability, power dependencies, work orders, and field results. Any unavailable term remains a gap; it is not estimated into false exactness.

## Open-PR boundaries

- PR #101 remains the candidate owner of canonical asset identity and impact-switchboard projection. Its relationship graph is not silently accepted as hydraulic truth.
- PRs #119/#121 remain the candidate owners of resource-balance contracts and uncertainty logic. Residuals remain non-proof.
- PR #125 remains the owner of stacked reservoir-specific balance entry gates; those gates can constrain future source/storage terms but cannot identify a distribution defect.
- PR #124 remains the candidate owner of the disabled water-crisis GUI bridge. It cannot auto-promote localization output.
- Current-main water-disruption ledgers remain the future incident-adapter boundary. This change does not modify incident truth or lifecycle state.

PR #126 is a separate offline FDA regulatory adapter and has no path or semantic overlap.

No file or implementation from an open PR is copied into this branch.

## Prohibitions

- no live PRASA/AAA polling;
- no scheduler activation;
- no API or GUI activation;
- no notification or public-alert activation;
- no valve, pump, treatment, or other control action;
- no production incident promotion;
- no model-only L4/L5 claim;
- no synthetic fixture represented as real Puerto Rico infrastructure evidence;
- no merge or auto-merge authorization.
