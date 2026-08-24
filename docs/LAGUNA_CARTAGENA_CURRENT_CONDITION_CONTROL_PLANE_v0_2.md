# Laguna Cartagena current-condition control plane v0.2

## Purpose

This control plane turns the documented Laguna Cartagena monitoring gap into a
provenance-safe, shadow-only operational lane. It does **not** claim that the
lagoon, outflow, groundwater, canal system, or water quality is normal or abnormal
when no eligible current measurement exists.

The implementation extends the existing water-disruption intake and console. It
does not create a second control surface, activate notifications, generate control
actions, or promote a current-condition alert from historical or nonrepresentative
data.

## Fixed target and coverage ledger

The versioned coverage ledger is
`config/laguna_cartagena_monitoring_coverage.v0.2.json`. It registers:

- USGS lake site `50129899`;
- USGS outflow site `50129900`;
- USGS well `180046067053700`;
- the relevant Lajas irrigation-canal gauges;
- NEON `LAJA` as nearby terrestrial context;
- NEON `GUIL` as explicitly ineligible to substitute for Lajas groundwater;
- USFWS, DRNA, AAA, and the Southwest irrigation operator as current provider or
  operational-record gaps until direct records are supplied.

Historical terminal dates remain explicit. A historical record may provide a
range or comparison baseline, but it is never current-condition eligible.

## Observation intake contract

The existing endpoint accepts a second envelope schema:

```text
POST /water-disruption/intake
Idempotency-Key: <operator supplied key>
X-Shadow-Mode: true
schema_version: aguayluz.laguna-cartagena-observation/v0.2
```

The complete JSON Schema is
`schemas/laguna-cartagena/v0.2/laguna_cartagena_observation.schema.json`.
Every observation must preserve an observation ID and window ID, source record
identifier, source SHA-256, provider, location, time, metric, value, unit,
evidence tier, direct/proxy classification, hydrologic representativeness, QA
state, evidence IDs, and shadow-mode status.

Derived fields are controlled by AguaYLuz and are rejected when supplied by an
upstream payload. These include freshness, current-condition eligibility, claim
scope, and eligibility reasons.

## Freshness and representativeness

Freshness is metric-specific:

- operational canal records: 36 hours;
- direct lagoon quantity and groundwater records: 72 hours;
- precipitation and soil context: 7 days;
- laboratory water-quality results: 45 days.

A direct target metric requires a direct measurement, direct hydrologic
representativeness, accepted or provisional QA, and a nonexpired validity window.
`GUIL` is always excluded from a Lajas-groundwater claim regardless of its quality
or recency.

## One-day field baseline

A complete current-condition field snapshot should use one synchronized observation
window and include:

- lagoon stage;
- outflow discharge;
- nearby groundwater level;
- specific conductance and temperature;
- dissolved oxygen, pH, and turbidity;
- nitrate, ammonia, and phosphorus;
- a fecal-indicator result.

The implementation provides the intake and evaluation contract. It does not
fabricate these measurements or claim that a field campaign occurred.

## Operational water balance

A water balance is computed only when one observation window contains eligible,
unit-compatible records for:

- canal release;
- treatment withdrawal;
- agricultural turnout;
- terminal flow.

Known leak flow is optional and remains separate from the unexplained residual.
All required records must be within 24 hours of one another and expressed in
`ft3/s`. Unsynchronized or mixed-unit records fail closed.

The residual is:

```text
release - treatment withdrawal - agricultural turnout - terminal flow - known leak flow
```

A positive unexplained residual is **not** a leakage finding. It produces a
candidate `conveyance_loss` hypothesis requiring field verification. A negative
residual is recorded as a contradiction. Exact zero is treated as balanced only
within the supplied records and does not prove that the canal is loss-free.

## Competing hypotheses

The materialized assessment keeps separate states for:

- source scarcity;
- allocated withdrawal;
- conveyance loss;
- measurement asynchrony;
- unknown.

Source scarcity may be supported only by an operator-authoritative threshold
record. A statistical anomaly remains a candidate. Confidence never converts a
candidate into a confirmed root cause.

## Read-only operator surface

`GET /water-disruption/incidents` now includes a `laguna_cartagena` control-plane
envelope. The existing `/water-disruption/console` renders:

- coverage gaps;
- current eligible observations;
- missing direct metrics;
- historical ranges when present;
- stale and representativeness exclusions;
- synchronization status;
- water-balance status;
- competing hypotheses, contradictions, and mitigation priorities.

The surface remains shadow-only. Notifications, production promotion, automatic
alerts, and control actions remain disabled.

## Overlap boundaries

This change does not duplicate or depend on the unmerged acquisition work in PRs
#109 or #116, and it does not depend on the unmerged asset switchboard in PR #101.
Those changes may later supply additional observations or asset context through
the same versioned contract after independent adjudication.
