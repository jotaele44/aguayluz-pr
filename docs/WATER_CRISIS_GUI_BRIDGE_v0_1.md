# Water Crisis GUI Bridge v0.1 — Design Only

## Scope

This package defines how provenance-grounded water-crisis assessments may be represented in the existing AguaYLuz alert GUI without granting an external watch, ChatGPT automation, or live provider authority to create verified alerts.

## Frozen base

- Base branch: `main`
- Base commit: `17c843595b5cdfbcef4e5f7b1ac6c662092e335d`
- Runtime activation: disabled
- Live AAA access: absent
- External watch writes: absent
- Automatic promotion: prohibited

## Candidate lifecycle

`external observation -> candidate assessment -> schema validation -> receipt/hash verification -> contradiction review -> operator/policy decision -> canonical alert`

The design-only mapper terminates at a candidate projection. It never writes to `data/alert_events.jsonl`, never calls the backend, never reloads the corpus, and never sets `review_status=accepted` or `status=active`.

## Assessment-to-alert mapping

| Assessment code | Module | Event type |
|---|---|---|
| CARRAIZO_RATIONING_RISK | HYDRO_OPS | hazard |
| CUPEY_DISTRIBUTION_RECOVERY_FAILURE | HYDRO_OPS | failure |
| ISLANDWIDE_RESERVOIR_DECLINE | HYDRO_OPS | hazard |
| LOCO_RESERVOIR_OBSERVATION | HYDRO_OPS | hazard |
| CONTAMINATION_EVENT | CONTAMINATION | quality |

## GUI contract

`WaterCrisisAssessmentPanel.jsx` is intentionally unwired. It renders assessment code, operational state, official-versus-derived status, municipalities, validity interval, likely causes, contradictions, restoration criteria, and immediate mitigation. It performs no fetch and activates no polling.

## Future activation gates

1. Implement an authenticated intake endpoint that only accepts candidate records.
2. Verify source receipt hashes and reject stale, malformed, replay-conflicting, or retracted inputs.
3. Add an operator decision record before promotion.
4. Persist the extension in a versioned canonical store compatible with the existing `AlertEvent` schema.
5. Add backend reload or database-backed reads.
6. Enable bounded GUI polling or server-sent events behind a disabled-by-default capability flag.
7. Add dedicated municipality and assessment-code filters and wire the panel into alert detail only after parity tests pass.
8. Keep official operational classifications visually distinct from AguaYLuz-derived assessments.

## Known design limitation

The existing `AlertEvent` schema has `additionalProperties=false`; therefore the `water_crisis_extension` cannot be inserted into canonical alerts until a versioned compatibility decision is approved. This PR deliberately leaves the component and mapper unwired rather than weakening the current schema.

## Safety and provenance invariants

- No live AAA adapter.
- No ChatGPT write path.
- No automatic verified promotion.
- No contamination promotion without official or technical evidence.
- No replacement of official reservoir thresholds with statistical proxies.
- Contradictions remain visible and unresolved until adjudicated.
- Stale or retracted candidates remain non-actionable.
