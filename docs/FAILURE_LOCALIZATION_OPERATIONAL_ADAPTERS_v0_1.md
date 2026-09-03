# AguaYLuz Failure-Localization Operational Adapters v0.1

## Status

Design and reference implementation only. The package is stacked on the exact certified failure-localization core from PR #128. It is offline-only, shadow-only, append-only, and incapable of issuing infrastructure control commands.

## Objective

Translate provenance-bound asset, hydraulic-topology, telemetry, incident, work-order, and field-result records into the existing failure-localization graph and observation contracts without allowing adapter output to bypass the L0-L5 evidence gates.

The adapter layer does not acquire PRASA/AAA records. It provides a contract for later operator-authorized records and a synthetic PRASA-style replay suite.

## Source record envelope

Every input must contain:

- `source_id`;
- `observed_at` and `received_at`, both timezone-qualified;
- canonical SHA-256 of the payload;
- `evidence_tier`;
- declared `freshness`;
- `quality`;
- `disclosure`;
- `authority`;
- `review_status`;
- an input kind and payload.

A record with a mismatched hash, invalid timestamp ordering, invalid quality, rejected review state, future graph state, stale graph state, or unresolved target is quarantined or rejected. The rejection is written to the append-only adapter receipt ledger.

## Supported adapters

| Input kind | Projection |
|---|---|
| `asset_identity` | Stable failure-graph asset with source alias, authority, evidence tier, and disclosure metadata |
| `hydraulic_topology` | Directed hydraulic edge; dependency or proximity records are not accepted as hydraulic truth |
| `pressure_zone_membership` | Explicit asset-to-pressure-zone and optional service-area binding |
| `flow` | Edge or asset flow observation |
| `pressure` | Asset pressure observation |
| `tank_level` | Tank-level observation with optional expected value and tolerance |
| `pump_state` | Pump-state observation |
| `valve_state` | Valve-state observation |
| `power` | Power-state observation |
| `production` | Treatment or facility production observation |
| `work_order` | Operator-record candidate assertion; does not auto-promote a candidate |
| `outage` / `restoration` | Service-state observations |
| `field_result` | Field or acoustic result; L5 still requires explicit promotion after L4 |

## Authority handling

`operator_authoritative`, `regulator_authoritative`, and `public_authoritative` may set the core observation `authoritative` flag only when the record is T1. `operator_declared` may establish a topology state but is not automatically an exact failure assertion. Secondary, inferred, and synthetic records remain non-authoritative.

A synthetic bundle must use `authority=synthetic_fixture` and `evidence_tier=T4` for every record. Synthetic field results are preserved as contract fixtures but cannot set `authoritative=true`, cannot set `field_confirmed=true`, and cannot support L4 or L5 promotion.

## Replay sequence

1. Reject active polling or credential-bearing configuration before any record is persisted.
2. Validate every record envelope and payload hash.
3. Append an admission, quarantine, or rejection receipt for every input.
4. Resolve source aliases to stable canonical asset and edge identifiers.
5. Quarantine conflicting source or canonical identifiers.
6. Materialize current asset identity, pressure-zone membership, and hydraulic topology.
7. Project admitted telemetry and operational records into core observations.
8. Run the certified shadow localization assessment.
9. Append a run receipt containing blockers, coverage counts, maximum operational grade, safety state, and the core assessment identifier.

## Fail-closed behavior

| Condition | Result |
|---|---|
| No admissible asset identity | L0 fail-closed run |
| Identifier conflict | Conflicted identity and dependent records removed; maximum operational grade L0 |
| Missing hydraulic topology | No mass-balance or pressure-path localization; maximum operational grade L2 when pressure-zone membership exists |
| Missing pressure-zone membership | Localization remains at system/service level unless independently supported |
| Stale telemetry | Preserved in the observation ledger but excluded from current diagnosis by the core freshness gate |
| Invalid payload hash | Input rejected and receipted; no diagnostic support |
| Unresolved asset or edge reference | Observation quarantined and receipted |
| Inferred topology | May support a bounded L3 candidate only with an explicit contradiction; never exactness |
| Synthetic field result | Non-authoritative and non-field-confirming |
| Any model output | Hard maximum L3 until explicit authoritative promotion |

## Offline fixture coverage

The fixture suite uses synthetic PRASA-style identifiers and covers:

- known transmission break;
- hidden leak or main-break candidate;
- pump failure;
- valve misconfiguration;
- tank depletion;
- power loss at a pumping asset;
- multicausal pump and valve event;
- unresolved outage;
- stale telemetry;
- payload-hash failure;
- identifier conflict;
- missing topology;
- synthetic field-result non-promotion;
- idempotent append-only replay;
- rejection of live credentials or polling configuration.

The fixtures are not records of PRASA, AAA, any municipality, or any Puerto Rico asset. Operational claims from them are forbidden.

## Ownership adjudication

- PR #101 remains the candidate owner of canonical utility-asset identity, aliases, disclosure, and dependency impact projection. Its dependency and proximity edges are not imported as hydraulic topology.
- PR #119 remains the architecture owner for balance lineage, quality, freshness, and non-proof semantics.
- PR #121 remains the implementation owner for resource-balance calculations and uncertainty. Adapter flow records may later feed that layer, but a residual remains an accounting signal rather than an exact defect.
- PR #124 remains the owner of the disabled water-crisis GUI bridge. This package does not add GUI, API, alert, or notification wiring.
- PR #125 remains the owner of reservoir-specific entry-gate packets. Reservoir readiness does not establish distribution failure location.
- PR #128 remains the owner of the localization core, diagnostics, ledgers, disclosure behavior, and L4/L5 gates. This package does not modify those files.

The machine-readable adjudication is in `docs/failure_localization_operational_adapter_overlap_matrix_v0_1.json`.

## Operational boundaries

The implementation contains no:

- HTTP, database, SCADA, MQTT, or vendor client;
- API key, token, password, or credential loader;
- live polling loop or scheduler registration;
- API or GUI route;
- alert, incident, notification, or federation-export activation;
- automatic L4 or L5 promotion;
- valve, pump, treatment, or other infrastructure-control command.

The operator view remains read-only and disabled by default through the certified core configuration.

## Activation gates

A later activation ballot must require all of the following:

1. merged and reconciled canonical asset identity;
2. operator-authorized hydraulic topology with version and effective interval;
3. source-specific credential design outside committed records;
4. current calibration and freshness policy for every telemetry class;
5. restricted-data disclosure review;
6. replay against independently verified historical incidents;
7. exact-head CI and security review;
8. separate authorization for any API, GUI, scheduler, notification, or production integration;
9. separate, explicit prohibition review before any control-system integration.

## Rollback

Rollback deletes only the ten additive adapter-module, schema, fixture, test, documentation, and overlap files. The PR #128 core and all current runtime, data, API, GUI, scheduler, alert, incident, notification, and federation paths remain unchanged.
