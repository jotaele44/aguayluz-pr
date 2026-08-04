# AguaYLuz Individual Reservoir Water-Balance Entry-Gate Packets v0.5

## Scope

This design-only package creates one independent entry-gate packet for every named reservoir system represented in the certified repository inventory. It extends PR #122 without merging or modifying PR #119, PR #122, or certification PR #123.

The package does **not** execute a balance. It defines the minimum evidence required before any reservoir can move to `entry_ready`.

## Reservoir universe

The confirmed main-branch USGS water-asset backbone names Carraízo/Loíza, La Plata, Guajataca, Patillas, Dos Bocas, Caonillas, Cerrillos, Cidra, Carite, Toa Vaca, Guayabal, and Lucchetti. A prior repository inventory also named Loco; because its exact source location was not re-established in this vector, Loco is retained as `candidate_repository_named_requires_reconfirmation` rather than silently omitted or promoted.

Each reservoir has an independent packet. Readiness, topology, stage-storage lineage, observations, and operator records are never inherited from another reservoir.

## Canonical entry boundary

Every packet requires four independently adjudicated boundary objects:

1. reservoir polygon;
2. contributing watershed;
3. downstream control section;
4. withdrawal and treatment boundary.

A name match, point location, municipality, proximity, power dependency, or `SUPPLIES` relationship is not hydraulic boundary evidence.

## Edge adjudication

Candidate inflow, outflow, withdrawal, controlled-release, spill, and transfer edges begin with:

```text
evidence_class = unresolved
balance_eligible = false
```

Promotion requires authoritative or operator-declared lineage, exact endpoint resolution, verified direction and semantics, an explicit accounting interval, compatible units/datums, and cleared contradiction review.

## Stage-storage curve registry

A reservoir level is not storage volume. Every packet therefore requires a versioned curve record containing:

- source and immutable source hash;
- vertical datum;
- effective dates;
- survey or sedimentation basis;
- interpolation and extrapolation policy;
- uncertainty bounds;
- supersession lineage.

Missing, stale, restricted, contradictory, or unversioned curves fail closed.

## Required accounting terms

Every reservoir packet independently evaluates:

- inflow;
- outflow;
- withdrawal;
- controlled release;
- spill;
- transfer;
- precipitation;
- evaporation;
- opening/closing storage state.

Each term is classified only as `present_eligible`, `present_ineligible`, `missing`, `restricted`, `stale`, `contradictory`, or `external_acquisition_required`.

A source receipt must bind the observation interval, temporal precision, quantity kind, unit, vertical datum, method, uncertainty, freshness, quality, source-equivalence key, source hash, and lineage.

## Initial adjudication

No reservoir is `entry_ready`.

Carraízo/Lago Loíza remains the selected reference pilot but stays `selected_blocked`. The other confirmed named systems are `packet_created_blocked`. Loco remains `universe_identity_review`.

Repository-named USGS asset or level evidence is treated as `present_ineligible` for storage state until exact site identity, datum, temporal alignment, and a versioned stage-storage curve are established. All other required accounting terms remain external acquisition dependencies unless independently adjudicated.

## Fail-closed fixtures

The fixture suite covers:

- missing stage-storage curve;
- unresolved topology;
- missing withdrawal;
- mixed datum;
- unsynchronized intervals;
- duplicate rainfall;
- absent uncertainty;
- restricted operator data.

Every fixture prohibits entry eligibility, balance execution, incident or alert promotion, and public or federation export.

## Governance hold

This package authorizes no live fetch, source-data write, database migration, runtime API or GUI, scheduler, alert, incident, notification, export, or automatic control action. A separate exact-head certification and a separate data-entry ballot are required before implementation.
