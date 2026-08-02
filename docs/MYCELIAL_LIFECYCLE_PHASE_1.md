# Mushroom site and lifecycle foundation — Phase 1

Phase 1 extends the Phase 0 occurrence ledger into a research-only field workflow for stable sites, repeated surveys, lifecycle observations, media evidence, environmental context, and confidence-aware state transitions.

## Entities

- `MushroomSite`
- `SurveySession`
- `LifecycleObservation`
- `MediaEvidence`
- `EnvironmentalSnapshot`
- `StateTransition`

Canonical Draft 2020-12 definitions are stored under `research/mycelial/schemas/` so this stacked PR does not claim admission to the production schema registry.

## Lifecycle states

`dormant_or_unknown → environmental_priming → emergence_suspected → fruiting_confirmed → expansion → peak → senescence → decomposition → post_fruiting`

The transition graph permits evidence-supported shortcuts and returns to unknown or priming after post-fruiting. It rejects biologically incoherent reverse transitions such as `peak → environmental_priming` within one fruiting episode.

## Observation boundary

The system tracks visible fruiting-body evidence and environmental context. It does not directly observe subterranean mycelial extent or continuity.

A negative survey is admissible only with positive effort, a method, and a completed end time. `not_detected` is never treated as confirmed ecological absence.

## Research console

The opt-in app serves `/research/mycelial/lifecycle/console`, containing:

- site-map surface with sensitive-coordinate warning;
- survey preparation form;
- lifecycle observation form;
- lifecycle-history table;
- weather-context panel;
- review queue.

The current console prepares records for review and does not silently persist browser input.

## Predictive boundary

`/research/mycelial/lifecycle/prediction/{capability}` always returns HTTP 503 and `model_not_calibrated`. No habitat score, exact location ranking, invented weights, infrastructure inference, notification, or control action is implemented.
