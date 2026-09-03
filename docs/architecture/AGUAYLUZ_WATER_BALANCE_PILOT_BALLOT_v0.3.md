# AguaYLuz water-balance implementation pilot ballot v0.3

Status: **design-only / implementation hold**  
Parent: PR #119 certified design head `5c3fcb3a5803773ad388b91afc5bc288d4fd4c80`  
Selected pilot: **Carraízo / Lago Loíza hydrologic-reservoir boundary**  
Activation state: **selected but blocked**

## 1. Ballot decision

Select the Carraízo / Lago Loíza system as the first bounded water-balance implementation target, limited initially to a shadow hydrologic-reservoir assessment.

This selection does not claim that the repository already possesses a complete mass balance. It identifies the target with the strongest currently materialized direct-observation foundation among the reviewed candidates:

- current main already ingests direct USGS reservoir-elevation and streamflow observations;
- the existing monitoring system explicitly treats Carraízo / Loíza as a marquee public-supply reservoir;
- current alert, incident, provenance, freshness, and review infrastructure already exists around the source records;
- PR #118's Laguna Cartagena package explicitly records that its direct current lagoon, outflow, groundwater, withdrawal, turnout, gate, leak, and terminal-flow terms remain unavailable.

Carraízo is therefore the better first **observation and projection** pilot. It remains blocked from producing an open or closed reservoir balance until the entry criteria below are satisfied.

## 2. Pilot scope

### Included boundary

- reservoir asset for Lago Loíza / Carraízo;
- directly associated USGS reservoir-level observation series;
- upstream and downstream stream-gage observations whose topology is independently adjudicated;
- quantitative precipitation observations over a documented contributing area;
- direct evaporation estimate or bounded model;
- approved stage-storage relationship;
- operator-reported withdrawals and controlled releases;
- explicit transfer terms when documented.

### Excluded from phase 1

- treatment-plant process balance;
- transmission mains;
- tanks and pressure zones;
- customer demand and non-revenue water;
- exact leak localization;
- incident or alert promotion;
- public balance publication;
- automated operational recommendations;
- any restricted control topology.

## 3. Entry criteria

The pilot may enter shadow implementation only when all code and governance prerequisites are met. It may enter balance evaluation only when all data prerequisites are met.

### 3.1 Code and governance entry

- PR #119 remains the controlling design contract.
- A dedicated implementation PR is created from an approved base.
- The PR #101 asset projector is implemented without treating dependency edges as hydraulic flow.
- Exactly one field-measurement producer and one annual-peaks producer exist.
- The USGS provider framework has reviewed live receipts for every endpoint used by the pilot.
- Source records remain unchanged; projections are append-only and reversible.
- No database migration is required for the first shadow lane.
- All balance outputs are denied to alerts, incidents, GUI, and federation by default.

### 3.2 Data entry

Required before a reservoir balance can be evaluated:

1. **Canonical boundary**
   - exact reservoir canonical asset;
   - contributing watershed boundary;
   - adjudicated inflow and outflow edges;
   - disclosure classification.

2. **Storage**
   - current reservoir elevation or direct storage observation;
   - versioned stage-storage curve;
   - curve datum and effective dates;
   - sedimentation or curve-revision lineage;
   - uncertainty bounds.

3. **Inflows**
   - eligible upstream flow observations or an approved runoff model;
   - quantitative precipitation over the documented area;
   - imported-transfer records when applicable;
   - groundwater inflow held as unknown unless measured or bounded.

4. **Outflows**
   - operator withdrawal records;
   - controlled-release records;
   - spill state;
   - downstream flow observations where representative;
   - transfer-out records when applicable.

5. **Atmospheric loss**
   - evaporation observations or a documented model;
   - method, interval, meteorological source, and uncertainty.

6. **Synchronization**
   - one declared accounting interval;
   - no date-only term mixed with hourly telemetry;
   - maximum time skew declared;
   - rate terms integrated before comparison with volume terms.

7. **Quality**
   - no unresolved unit or datum conflict;
   - no duplicate source-equivalence group inside one term set;
   - no missing required term silently set to zero;
   - provisional observations explicitly flagged.

If any required item is absent, the only permitted closure state is `underdetermined` or `not_evaluated`.

## 4. Exit criteria

The pilot is successful when it demonstrates, on shadow data only:

- deterministic source-to-canonical projection;
- complete lineage from every balance term to source records and hashes;
- exact unit conversion and rate integration;
- uncertainty propagation;
- freshness and synchronization enforcement;
- source-equivalence deduplication;
- correct handling of positive, negative, missing, stale, contradictory, meter-reset, time-skew, unit-error, and underdetermined fixtures;
- reproducible closure classification;
- first-failed-boundary behavior;
- residual language that remains non-accusatory and model-only;
- byte-stable or cryptographically receipted outputs;
- zero mutation of source records and zero production side effects.

Completion of these criteria authorizes only a review of the next implementation phase. It does not authorize operational use.

## 5. Fail-closed criteria

The pilot must return `underdetermined`, `contradictory`, or `not_evaluated` when any of the following occurs:

- missing stage-storage curve;
- missing operator withdrawal or release term;
- unresolved inflow or outflow topology;
- date-only and hourly records mixed in one balance;
- incompatible units or datums;
- precipitation product overlap or double counting;
- the same USGS source-equivalence group enters more than once;
- field measurement carries pumping or unknown qualifiers when a static level is required;
- reservoir elevation is treated as volume without a curve;
- groundwater level is treated as storage without aquifer properties;
- uncertainty bounds are absent for a modeled term;
- a restricted topology record would be exposed outside the operator boundary;
- source receipt or source hash is absent;
- a residual is being used to create an incident, alert, public claim, or wrongdoing attribution.

## 6. Rollback criteria

Rollback is mandatory when:

- source rows are rewritten or deleted;
- canonical IDs are unstable across identical inputs;
- a producer creates orphan source foreign keys;
- duplicate USGS producers materialize the same collection;
- a prefix-wide asset replacement removes assets referenced by retained readings;
- a balance output reaches an existing alert, incident, GUI, scheduler, or federation path;
- restricted asset or topology detail appears in a public output;
- a model residual is labeled as measured physical loss;
- a test fixture can bypass the fail-closed state;
- a branch or base drift invalidates the approved contract.

Rollback means disabling the shadow projector or removing its derived outputs. Source observations and existing AguaYLuz runtime behavior remain untouched.

## 7. Laguna Cartagena secondary role

Laguna Cartagena remains the secondary contract-validation target because it has superior explicit controls for:

- historical-only observations;
- direct versus proxy classification;
- hydrologic representativeness;
- stale exclusions;
- missing operator records;
- synchronized-window gating;
- non-proof candidate conveyance-loss language.

It should be used to prove that the engine correctly refuses to calculate a current operational balance when the required terms are missing.

## 8. Approval boundary

This ballot approves only the architecture of a later, disabled implementation PR. It does not approve code execution against live providers, scheduling, database writes, API or GUI routes, alerts, incidents, notifications, public exports, or merge of any reviewed PR.
