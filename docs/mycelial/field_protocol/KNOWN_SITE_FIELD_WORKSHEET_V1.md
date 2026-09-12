# Known-site mushroom field worksheet v1

Classification: **FIELD CAPTURE TEMPLATE / NOT A BIOLOGICAL RECORD UNTIL COMPLETED AND REVIEWED**

This worksheet mirrors the `schemas/mycelial-field/v1/` design contracts. It contains no exact-coordinate field and does not authorize collection, prediction, or public disclosure of sensitive locations.

## Before the visit

- Site ID: `MYC_SITE_...`
- Stable site key already registered: yes / no
- Site review state: needs_review / protocol_eligible / rejected / retired / superseded
- Location mode: generalized / withheld
- Sensitivity: ordinary_research_site / sensitive / sensitivity_unresolved
- Access/permission state: verified_permitted / public_access_subject_to_rules / permission_required / withheld / expired
- Permission reference, if required:
- Target ID: `MYC_TGT_...`
- Target kind: taxon / guild / morphotype / all_macrofungi
- Target definition/reference:
- Protocol ID and version:
- Scheduled visit time:
- Timezone: `America/Puerto_Rico` unless another explicit zone applies

**Do not write exact latitude/longitude on this worksheet.**

## Visit execution

- Survey ID: `MYC_SUR_...`
- Actual start time:
- Actual end time:
- Search geometry type: plot / transect / route / bounded_area / site_reference
- Generalized search reference:
- Observer count:
- Observer pseudonyms:
- Observer qualification classes:
- Person-minutes completed:
- Equipment used:

### Coverage actually searched

- Substrates:
- Hosts:
- Deadwood classes:
- Microsites:

### Constraints

Record conditions that altered detectability, effort, safety, or protocol completion. Examples may include access closure, heavy rainfall, unsafe terrain, poor visibility, equipment failure, or interruption. Do not convert a constrained or incomplete visit into a negative survey.

Constraints observed:

## Visit disposition

Choose one visit status:

- [ ] completed
- [ ] incomplete
- [ ] aborted
- [ ] missed

Choose one target-detection status:

- [ ] detected
- [ ] not_detected
- [ ] not_assessed

### Required logic

- `not_detected` is valid **only** when the visit was completed with positive search effort.
- A valid non-detection means only: **documented non-detection under stated effort; not proof of absence**.
- `missed` must be `not_assessed` with zero completed effort.
- `aborted` or `incomplete` may preserve a real detection, but lack of detection is not promoted to `not_detected`.
- Detecting one target does not imply absence of other taxa.

Outcome reason, required for incomplete/aborted/missed visits:

## If target fruiting bodies were detected

Create one or more fruiting-observation records. Do not create a fruiting-observation object for a non-detection.

For each observation:

- Observation ID: `MYC_FOBS_...`
- Observed time:
- Visible state: primordia / emerging / expanding / mature / senescent / decomposing / unresolved
- State basis:
- Taxonomic assertion ID, if available: `MYC_TAX_...`
- Substrate observed:
- Host observed:
- Media IDs:

### Episode identity

- Episode identity state: unassigned / candidate / adjudicated
- Episode ID, only when assigned: `MYC_EPI_...`
- Evidence basis for candidate/adjudicated relationship:

Nearby or temporally adjacent fruiting bodies do not automatically belong to one fruiting episode.

### Individual fruiting-body identity

- Identity state: unassigned / candidate / adjudicated
- Fruiting-body ID, only when assigned: `MYC_FB_...`
- Identity basis: none / photo_sequence / tagged_marker / field_landmark / combined_evidence

Do not calculate physical growth between visits unless the same measurement unit is defensibly bound across observations.

### Count

- Count method: exact / minimum_estimate / range / unknown
- Exact value, if applicable:
- Lower bound, if applicable:
- Upper bound, if applicable:

Do not replace an unknown count with zero.

### Optional physical measurements

For each measurement record:

- Measurement ID: `MYC_MSR_...`
- Metric: cap_diameter / height / stipe_diameter / cluster_span / occupied_area / other
- Value:
- Unit:
- Measurement method:
- Scale evidence reference, if any:
- Estimated measurement uncertainty, if available:

A measurement is evidence. It is not a growth-rate estimate until repeated measurements pass the individual/unit identity gate.

## Media handling

- Preserve original media identity and hash in the approved evidence workflow.
- Record observation-data rights and media rights separately.
- Strip or withhold location-bearing metadata before any generalized/public derivative.
- Do not infer taxonomic certainty from image count or map precision.

## Environmental notes

Field observations may preserve contemporaneous notes or authorized sensor readings, but this worksheet does not declare model predictors. Environmental feature admission, temporal/as-of alignment, lag windows, uncertainty, and leakage controls belong to W11.

Environmental/context notes:

## End-of-visit review

Before marking a field record `protocol_eligible`, confirm:

- [ ] Site and target IDs existed before interpretation of the outcome.
- [ ] No exact-coordinate field was inserted into the interchange record.
- [ ] Observer count equals the number of observer pseudonyms.
- [ ] Start time is not after end time.
- [ ] Person-minutes reflect completed effort rather than scheduled effort.
- [ ] Coverage records describe what was actually searched.
- [ ] Missed/incomplete/aborted visits were not converted to negatives.
- [ ] `not_detected`, if used, has completed positive effort.
- [ ] Fruiting observations exist only for visible evidence.
- [ ] Episode and individual identity are not inferred from proximity alone.
- [ ] Measurements retain units and methods.
- [ ] Taxonomic evidence remains separately reviewable.
- [ ] Media rights and sensitive metadata remain separately controlled.

## Scientific boundary

This worksheet supports evidence collection for a future known-site detection/phenology model. It does **not** establish:

- ecological absence;
- underground mycelial extent or continuity;
- environmental causation;
- habitat suitability;
- a mushroom location ranking;
- a calibrated probability;
- physical growth rate without repeated identity-bound measurements.
