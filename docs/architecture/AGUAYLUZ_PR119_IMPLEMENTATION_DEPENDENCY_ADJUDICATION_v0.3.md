# AguaYLuz PR #119 implementation-dependency adjudication v0.3

Status: **design-only stacked ballot**  
Parent design: PR #119, certified head `5c3fcb3a5803773ad388b91afc5bc288d4fd4c80`  
Runtime activation: **not authorized**  
Merge authorization: **none**

## 1. Decision scope

This document adjudicates the implementation dependencies identified by the certified integrated water-balance architecture. It does not merge or copy the full implementation of PR #101, #109, #116, or #118. It selects reusable contracts, rejects unsafe semantic shortcuts, and defines the minimum transformations required before a shadow implementation may be proposed.

The parent rules remain controlling:

- source records remain authoritative in their existing roles;
- canonical water-balance records are projections with lineage;
- dependency and proximity edges are not hydraulic flow evidence;
- provider coverage is not observation coverage;
- date-only records are not silently promoted to instant telemetry;
- model residuals are not proof of leakage, theft, diversion, illegal pumping, falsified reporting, or operator misconduct;
- no alert, incident, GUI, scheduler, database, or federation behavior is activated by this ballot.

## 2. PR #101 asset identity and relationship adjudication

PR #101 provides a useful candidate asset canonicalization layer, alias crosswalk handling, public/operator disclosure boundary, contradiction channel, and a typed relationship vocabulary. It is not directly reusable as the hydraulic topology for a water balance.

### 2.1 Asset decision

**Disposition: ADAPT.**

The following concepts may be reused through a projector:

- source asset IDs and aliases;
- deterministic canonical grouping from existing crosswalk clusters;
- provenance class;
- identifier quality;
- positional uncertainty;
- public versus operator-restricted disclosure;
- contradiction and coverage-gap reporting.

The PR #101 canonical ID is not the water-balance canonical ID. The projector must emit `AYL_WBA_*` records and preserve every PR #101 or source ID in `source_asset_ids` and `aliases`. Asset identity does not establish balance-boundary eligibility.

### 2.2 Relationship decision

PR #101 currently defines `UPSTREAM_OF`, `DOWNSTREAM_OF`, `SUPPLIES`, `DEPENDS_ON`, `POWERED_BY`, `BACKUP_FOR`, `LOCATED_IN`, `SERVES`, and `MONITORED_BY`. Its runtime also maps the source term `energizes` into `SUPPLIES`, and permits impact propagation over `UPSTREAM_OF`, `SUPPLIES`, and `BACKUP_FOR`.

Impact propagation and hydraulic balance eligibility are separate decisions. No PR #101 relationship is balance-eligible merely because impact propagation is allowed.

| PR #101 relationship | Default implementation class | Hydraulic eligibility rule |
|---|---|---|
| `UPSTREAM_OF` | `unresolved` until evidence review | May become `hydraulic_eligible` only when both endpoints are water assets, direction is source-declared or independently corroborated, `inferred=false`, and lineage identifies the authoritative topology record. Otherwise `inferred`. |
| `DOWNSTREAM_OF` | `unresolved` until evidence review | Same requirements as `UPSTREAM_OF`; inverse pairs must be checked for contradiction and duplicate identity. |
| `SUPPLIES` | `dependency_only` by default | May become `hydraulic_eligible` only after the original source vocabulary is preserved and shown to mean water conveyance. Any edge originating from `energizes` remains `dependency_only`. |
| `DEPENDS_ON` | `dependency_only` | Never balance-eligible without a separate hydraulic edge. |
| `POWERED_BY` | `dependency_only` | Energy dependency only; never a water-flow edge. |
| `BACKUP_FOR` | `dependency_only` | Backup relationship does not prove an open interconnection, direction, capacity, or actual transfer. A separate operator-declared transfer edge is required. |
| `LOCATED_IN` | `dependency_only` | Spatial containment only. |
| `SERVES` | `dependency_only` | Service association does not establish a metered flow boundary. It may support a service-area mapping but not a flow term. |
| `MONITORED_BY` | `dependency_only` | Observation association only. |
| unknown or unmapped vocabulary | `unresolved` | Must remain a coverage gap; no inferred hydraulic mapping. |

### 2.3 Required FlowEdge projector

A PR #101 relationship may be projected to a PR #119 `FlowEdge` only after adding:

- a distinct `AYL_WBE_*` identity;
- original relationship vocabulary before normalization;
- endpoint canonical-asset crosswalks;
- `topology_state` of `authoritative`, `declared`, `inferred`, `unresolved`, or `restricted`;
- `balance_eligible` and explicit eligibility reasons;
- source record IDs, source references, hashes, and source-equivalence group;
- evidence tier and review status;
- restricted-disclosure state;
- contradiction checks for reverse, duplicate, missing-endpoint, and semantic-collision edges.

A confidence score cannot substitute for any of these requirements.

### 2.4 PR #101 implementation hold

Do not merge the PR #101 backend or GUI into a water-balance implementation through this ballot. The reusable unit is the asset/relationship projection contract. The existing impact switchboard may later consume generalized balance findings, but it cannot become the ledger store or balance engine.

## 3. PR #109 and PR #116 USGS overlap adjudication

PR #109 and PR #116 both add `scripts/ingest_usgs_field_measurements.py`, `scripts/ingest_usgs_peaks.py`, refresh-plan changes, and GUI capability declarations. They must not coexist as independent producers for the same USGS collections.

### 3.1 Selected acquisition architecture

**One producer per USGS collection.**

Use PR #116 as the provider-framework base for:

- shared USGS endpoint constants;
- environment-only `USGS_API_KEY` handling;
- bounded OGC pagination;
- ten-category provider-coverage matrix;
- source receipts;
- category validation;
- explicit separation between `implemented_unverified_live` and verified live coverage.

Adapt the PR #109 field-measurement semantics into that framework:

- calendar-year slicing for statewide field-measurement queries;
- monitoring-location metadata lookup;
- one-site-at-a-time lookup when repeated monitoring-location IDs are not honored;
- calendar date from `year`, `month`, and `day` before any timestamp fallback;
- default parameter `72019` only;
- parameter `62610` opt-in and semantically isolated;
- `Static` as the only known-clean qualifier, with unknown or pumping states flagged rather than guessed;
- negative values retained for flowing-artesian conditions;
- reading identity that distinguishes repeat visits and reading type while excluding the mutable value;
- source hashes that include the measurement semantics;
- incremental asset merge by exact asset ID rather than prefix-wide replacement;
- location, municipality, datum, well-depth, and aquifer metadata preservation when supplied.

Adapt the PR #109 annual-peaks semantics into the PR #116 framework:

- separate discharge and stage records;
- identity includes site, water year, parameter, date, and qualifier set;
- stage-at-peak-discharge and annual-maximum-stage records remain distinct;
- value caveat qualifiers are retained and drive review state;
- annual peaks do not create duplicate source assets when a monitoring-location registry can resolve the site;
- source receipts and bounded pagination come from the PR #116 framework.

### 3.2 Rejected combinations

The following combinations are rejected:

- running both PR #109 and PR #116 field-measurement scripts;
- running both peak scripts;
- prefix-wide deletion of `USGSFM_*` assets during a narrowed acquisition window;
- using provider-registration status as current observation freshness;
- mixing `62610` elevation-above-datum with `72019` depth-below-land-surface in one drawdown series;
- collapsing peak-stage records solely by site, parameter, water year, and date;
- treating a date-only monitoring reading as hourly or instantaneous telemetry;
- copying PR #109's unrelated NHC and NEON changes into the USGS implementation lane.

### 3.3 Asset-prefix and canonical identity decision

Producer namespaces remain source-level identifiers:

- `USGS_*`: surface-water and general monitoring-location assets;
- `USGSGW_*`: daily-values groundwater assets;
- `USGSFM_*`: discrete field-measurement well assets;
- other existing producer prefixes remain unchanged.

`USGSFM_*` is retained for discrete field-measurement producer ownership. It must not flip to `USGSGW_*` based on another producer's current daily-values coverage.

All producer IDs for the same USGS monitoring location are mapped to one `AYL_WBA_*` canonical asset only after identity review. The source-equivalence group is:

```text
usgs:monitoring-location:<bare_site_number>
```

This crosswalk prevents double counting while preserving producer lineage. It does not assert that every measurement has the same datum, temporal precision, parameter meaning, or balance eligibility.

### 3.4 Observation projection decision

USGS source rows continue to validate as existing `monitoring_reading` records. A separate projector emits `WaterObservation` records with:

- exact source reading ID and source hash;
- source-equivalence group;
- parameter code and datum;
- quantity kind;
- source and normalized units;
- interval start and end;
- temporal precision;
- uncertainty method and bounds;
- freshness state;
- quality flags;
- balance eligibility and exclusions.

A daily-value row projects with day precision. A field measurement projects as an instant only when the retained raw source record contains a real observation time; otherwise it projects with day precision. Annual peaks are historical cross-validation observations and are not current water-balance terms.

## 4. PR #118 Laguna Cartagena fit assessment

PR #118 is a strong candidate for a **gap-control-plane and contract-adapter pilot**, but not the first operational mass-balance pilot.

### 4.1 Compatible controls to adapt

- direct, proxy, and context classification;
- hydrologic representativeness;
- explicit historical-baseline state;
- metric-specific validity windows;
- no stale-to-current promotion;
- explicit exclusion of NEON GUIL as a Lajas-groundwater substitute;
- synchronized-window requirement;
- mixed-unit fail-closed behavior;
- separate known-leak term and unexplained residual;
- positive residual classified only as candidate conveyance loss;
- negative residual classified as contradiction;
- no automatic alerts, notifications, incident promotion, or control action;
- explicit external data gaps.

### 4.2 Required adaptations before ledger use

PR #118 observations require a projector that adds the parent contract's:

- `Quantity` kind, normalized value, normalized unit, and datum;
- interval start, interval end, and temporal precision;
- numeric uncertainty object and correlated-error group;
- full freshness object;
- quality flags including time skew, unit error, contradiction, and double-counting state;
- lineage parents, transformation IDs, and source-equivalence group;
- balance eligibility and exclusion reasons.

Its water-balance and synchronization objects must become strict versioned contracts rather than unconstrained objects. Rate terms must share an explicit interval and represent either a rate snapshot or an integrated volume; the two cannot be mixed.

### 4.3 Pilot decision for Laguna Cartagena

**Disposition: ADAPT as secondary contract pilot; HOLD as first operational balance pilot.**

PR #118 explicitly records that direct current lagoon stage, outflow, nearby groundwater, treatment withdrawals, agricultural turnouts, gate states, known leaks, and terminal flow remain unavailable. That is valuable observability truth, but it means the operational balance entry gate is not satisfied.

Laguna Cartagena should be used to test:

- missing-data behavior;
- stale and proxy exclusions;
- synchronized-window gating;
- projection of direct versus contextual observations;
- underdetermined and contradictory assessment states;
- non-proof residual language.

It must not be used to claim a current conveyance-loss estimate until the required operator and field records are present.

## 5. Adjudication result

| Dependency | Decision | Implementation effect |
|---|---|---|
| PR #101 asset identity | `ADAPT` | Build a canonical Asset projector; retain source IDs and disclosure rules. |
| PR #101 relationships | `ADAPT/HOLD` | Project only after per-edge hydraulic eligibility adjudication. |
| PR #109 field measurements | `ADAPT` | Preserve hardened parsing, identity, qualifier, and merge semantics. |
| PR #109 annual peaks | `ADAPT` | Preserve qualifier-aware identity and historical semantics. |
| PR #116 shared client and coverage | `ADAPT` | Use as the single USGS provider framework and receipt layer. |
| Duplicate PR #109/#116 producers | `REJECT` | Exactly one producer per collection. |
| PR #118 observation and freshness controls | `ADAPT` | Project into the canonical observation contract. |
| PR #118 as first operational pilot | `HOLD` | Use as a missing-data/control-plane validation case only. |

## 6. Implementation boundary

This adjudication authorizes only a later implementation proposal. It does not authorize:

- merging any reviewed PR;
- live polling;
- source-data or database writes;
- scheduler changes;
- new API routes;
- GUI activation;
- alerts or notifications;
- incident promotion;
- public or federation export;
- operator-control integration.
