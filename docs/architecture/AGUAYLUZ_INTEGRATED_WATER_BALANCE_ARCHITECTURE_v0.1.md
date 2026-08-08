# AguaYLuz Integrated Water Balance Architecture v0.1

Status: **Design only / proposed**  
Pinned repository base: `main@17c843595b5cdfbcef4e5f7b1ac6c662092e335d`  
Runtime activation: **prohibited by this change**

## 1. Mission

Reconcile the existing hydrologic, groundwater, reservoir, treatment, infrastructure, incident, freshness, provenance, impact, alert, GUI, and federation components into one additive water-movement ledger and a family of nested mass-balance contracts.

This design does not replace the existing source records. It defines a compatibility layer that can project existing records into a common analytical model while retaining their original identifiers, schemas, files, evidence tiers, review states, and hashes.

## 2. Non-goals and hard boundaries

This design does **not**:

- remove or rewrite `utility_asset`, `monitoring_reading`, `service_event`, alert, incident, or source-manifest records;
- activate live ingestion, polling, notifications, automated incident promotion, or infrastructure control;
- infer illegal pumping, theft, diversion, leakage, or operator misconduct from a residual alone;
- treat rainfall as direct reservoir inflow without a documented runoff, recharge, and lag model;
- treat reservoir elevation as storage volume without a stage-storage relationship;
- merge incompatible units, time intervals, datum conventions, or groundwater parameters;
- use open pull-request code as if it were part of current `main`;
- expose restricted infrastructure coordinates or control topology.

## 3. Existing truth layers to preserve

### 3.1 Static and slowly changing assets

`schemas/utility_asset.schema.json` and `data/utility_assets.jsonl` remain the source-level asset corpus. The water-balance asset definition adds canonical hydrologic roles, aliases, topology status, disclosure class, and migration lineage without mutating source records.

### 3.2 Routine observations

`schemas/monitoring_reading.schema.json` remains the current daily observation backbone. Its records are projected into `WaterObservation` records. Projection must preserve the source reading ID and must not silently increase temporal precision from date-only to timestamp precision.

### 3.3 Events, alerts, and incidents

`service_event`, alert schemas, monitoring incident ledgers, and the append-only water-disruption service remain event truth systems. A balance residual may create an analytical finding only. It cannot create a confirmed incident without the existing validation and lifecycle policy.

### 3.4 Provenance and federation

Source manifests, hashes, evidence tiers, review queues, integration reports, and federation exports remain authoritative for provenance and external publication. Water-balance products are ineligible for federation export until a later compatibility and privacy ballot explicitly authorizes them.

## 4. Canonical model

The canonical model is a directed, time-aware graph:

```text
WaterBalanceAsset --WaterFlowEdge--> WaterBalanceAsset
        |                                  |
        +---------- WaterObservation ------+
                           |
                    WaterLedgerEntry
                           |
                   NestedBalanceWindow
                           |
                  BalanceAssessment
```

### 4.1 Asset

A canonical asset represents a system boundary or physical/administrative water component, including watershed, reservoir, stream, canal, aquifer, well, intake, treatment plant, pump station, tank, main, interconnection, pressure zone, service area, outfall, consumer group, and environmental sink.

A canonical asset must retain:

- all source asset IDs and aliases;
- operator and municipality when supported;
- source-record references and evidence state;
- spatial uncertainty and disclosure class;
- topology state: `authoritative`, `declared`, `inferred`, `unresolved`, or `restricted`;
- whether the asset is eligible to define a formal balance boundary.

### 4.2 Flow edge

A flow edge states that water may move between two assets. Edge types include inflow, outflow, withdrawal, transfer, release, recharge, seepage, evaporation, return flow, treatment production, distribution, consumption, and loss.

An edge is not evidence that flow occurred. Actual flow requires an observation or ledger entry. Inferred or proximity-derived edges cannot be used as confirmed hydraulic topology.

### 4.3 Observation

Every observation carries:

- the observed asset or edge;
- phenomenon, value, unit, and datum where relevant;
- exact interval or explicitly date-only precision;
- `observed`, `estimated`, `modeled`, or `derived` method class;
- uncertainty, freshness, quality, and lineage objects;
- balance eligibility and explicit exclusion reasons.

Observed facts, derived quantities, and interpretations are separate records.

### 4.4 Ledger entries

The ledger recognizes six physical accounting entry types:

1. `storage_state`
2. `withdrawal`
3. `transfer`
4. `release`
5. `consumption`
6. `loss`

A `loss` entry may be `measured_physical`, `authorized_unbilled`, `apparent_metering`, `model_residual`, or `unresolved`. A model residual is never promoted to measured physical loss without corroboration.

### 4.5 Uncertainty, freshness, quality, and lineage

These controls are first-class and cannot be replaced by a single confidence score.

- **Uncertainty** records numeric bounds, distribution assumptions, method, and correlated-error group.
- **Freshness** records `observed_at`, `valid_until`, state, and eligibility.
- **Quality** records provisional status, meter resets, time skew, unit normalization, contradiction state, and review disposition.
- **Lineage** records source IDs, source hashes, transformation IDs, code version, parent records, and direct/derived status.

## 5. Nested balance hierarchy

A balance is calculated only inside an explicit boundary and interval. The architecture supports six nested balance types.

### 5.1 Watershed

```text
precipitation + imported_surface_flow
- evapotranspiration - exported_surface_flow
- recharge - change_in_surface_storage
= watershed_residual
```

Rainfall must be converted to effective water input through a documented area, runoff/recharge coefficient or process model, antecedent conditions, and travel-time lag. Radar and gauges remain separate observations until reconciled.

### 5.2 Reservoir

```text
measured_inflow + direct_precipitation + groundwater_inflow + transfers_in
- withdrawals - controlled_releases - spill - evaporation - seepage - transfers_out
- change_in_storage
= reservoir_residual
```

Storage change requires an approved stage-storage curve or direct volumetric observation. Sedimentation and curve version are part of lineage.

### 5.3 Groundwater

```text
recharge + lateral_inflow + return_flow
- pumping - spring_discharge - coastal_or_lateral_outflow
- change_in_groundwater_storage
= groundwater_residual
```

Water-level change is not storage change without aquifer geometry and storage coefficient or specific yield. Static, pumping, and datum-inverted groundwater measurements remain distinct.

### 5.4 Treatment plant

```text
raw_water_intake
- finished_water_output - backwash - sludge_water - process_use - bypass_or_reject
= treatment_residual
```

Intake and output must be synchronized to the same interval. Plant process water cannot be counted both as consumption and release.

### 5.5 Transmission

```text
plant_output + interconnections_in
- tank_storage_change - pressure_zone_inputs - interconnections_out - authorized_operational_use
= transmission_residual
```

Topology must be operator-declared or independently corroborated before a specific pipe, valve, or interconnection is blamed.

### 5.6 Distribution

```text
zone_input + tank_drawdown
- metered_consumption - authorized_unbilled_use - exports
= distribution_residual
```

The residual may contain real leakage, meter under-registration, timing mismatch, unauthorized use, or missing records. The architecture reports these as candidate classes with bounded confidence, not proof.

## 6. Balance closure and anomaly states

Each balance window resolves to one of:

- `closed`: residual is negligible under the declared policy;
- `within_uncertainty`: residual is non-zero but inside the combined uncertainty envelope;
- `open`: residual exceeds the envelope and required coverage is present;
- `underdetermined`: required terms or topology are missing;
- `contradictory`: mutually incompatible eligible observations exist;
- `not_evaluated`: policy or freshness gate prevented evaluation.

A residual is promoted to an analytical anomaly only when it has sufficient magnitude, persistence, temporal alignment, coverage, and independent corroboration.

## 7. First-failed-boundary localization

Balances are evaluated upstream to downstream. The first boundary that fails while its parent balance closes narrows the investigation scope.

Example:

```text
watershed: within_uncertainty
reservoir: closed
treatment: closed
transmission: open
distribution: underdetermined
```

This supports a transmission-system investigation but does not identify an exact pipe failure.

## 8. Double-counting controls

The engine must reject or quarantine:

- the same observation entering multiple terms in one balance;
- raw intake and derived finished-water production being counted as independent source inflows;
- cumulative meter totals mixed with interval volumes without differencing lineage;
- overlapping spatial rainfall products summed together;
- tank storage change counted both in transmission and distribution without boundary ownership;
- releases classified simultaneously as environmental flow, treatment withdrawal, and loss;
- private-well pumping duplicated across permit, facility, and USGS aliases;
- estimated and observed versions of the same quantity used together without supersession.

Every term receives a balance-window membership key and a source-equivalence group.

## 9. Temporal and unit policy

- The canonical accounting unit is cubic metres for volume and cubic metres per second for rate; source units are preserved.
- Conversion requires a recorded transform and exact factor.
- Rates require interval integration before comparison with volume.
- Date-only readings cannot be synchronized to hourly telemetry.
- Clock source, timezone, daylight-saving policy, and maximum skew are explicit.
- Meter resets and rollover are events, not negative consumption.
- Missing intervals are not interpolated unless the method, maximum gap, and uncertainty penalty are declared.

## 10. Cause-attribution ladder

An open residual may be classified as:

1. data-quality or timestamp defect;
2. unit/datum or storage-curve defect;
3. missing operational record;
4. modeled hydrologic-process gap;
5. authorized but unmetered use;
6. apparent metering loss;
7. candidate physical loss;
8. candidate unrecorded abstraction;
9. unresolved.

Classification strength is limited by the weakest supporting evidence. Exact-location or wrongdoing claims require field or operator corroboration.

## 11. Integration with open pull requests

Open PRs are inputs to compatibility review, not dependencies of this design branch.

- PR #101: candidate canonical asset graph and impact switchboard; map to Asset and FlowEdge after adjudication.
- PR #96: candidate provider registry; map to source/provider coverage, not observations.
- PR #109 and #116: overlapping USGS acquisition and coverage work; reconcile before promotion and preserve distinct parameter semantics.
- PR #118: candidate Laguna Cartagena control plane; use as a pilot mapping after merge adjudication.
- PR #114/#115: cave/karst assets and GUI; hydrologic relations remain typed contextual edges, not assumed balance flows.
- PR #104-#108: rescued WIP; review for unique contracts only and never merge wholesale through this architecture vector.

## 12. Security and disclosure

The public analytical layer must fail closed for operator-restricted wells, valves, SCADA points, feeder assignments, and exact control topology. Balance results may be generalized to a system or pressure-zone boundary. Raw restricted records remain outside public federation exports.

## 13. Acceptance gates for later implementation

Implementation cannot begin until review confirms:

- exact canonical IDs and crosswalk policy;
- interval, unit, datum, and uncertainty rules;
- source precedence and supersession policy;
- open-PR overlap adjudication;
- restricted-topology disclosure policy;
- pilot system and minimum telemetry coverage;
- shadow-only output paths and rollback plan.

No runtime, database, alert, GUI, or exporter behavior is changed by v0.1.