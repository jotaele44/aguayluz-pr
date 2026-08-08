# Patillas–Guayama Frozen Water-Balance Regression Pilot v0.2

**Status:** design-only, frozen regression evidence  
**Parent PR:** #121  
**Pinned main:** `17c843595b5cdfbcef4e5f7b1ac6c662092e335d`  
**Runtime activation:** none

## Selection decision

The Patillas–Guayama chain was selected after comparing the observable coverage of the strongest candidates.

| Candidate | Rainfall | Inflow | Reservoir state | Release/operations | Treatment boundary | Downstream/intake | Decision |
|---|---|---|---|---|---|---|---|
| Patillas–Guayama | Direct dam-site precipitation | Upstream USGS discharge | Reservoir elevation | Three gate openings and canal forebay | USGS gauges above and below Guayama Filtration Plant | Gauge above AES intake and named intake/downstream assets | Selected |
| Carraízo/Lago Loíza | Partial regional context | Multiple upstream gauges | Multiple reservoir stations | Downstream dam gauge | No equally explicit synchronized above/below treatment pair in the current corpus | Broad downstream gauge coverage | Retained as follow-up |
| Lajas irrigation chain | NEON/regional context | Canal gauges | Source-reservoir linkage incomplete in this corpus | Strong canal sequence | Above/below Lajas and Majinas plant gauges | Canal terminal coverage | Retained as follow-up |

Selection does not mean the Patillas chain has a complete balance. It has the best **structural observation coverage**, but the frozen records are asynchronous and omit storage change, direct treatment withdrawal, terminal flow, and a validated loss model.

## Frozen evidence

Seven canonical source extracts are committed and SHA-256 bound by `source_manifest.json`:

- USGS 50092000 upstream discharge;
- USGS 50093045 reservoir elevation, precipitation, and temporary gate-opening state;
- USGS 50093053 forebay discharge;
- USGS 50093075 discharge above Guayama Filtration Plant;
- USGS 50093078 discharge below Guayama Filtration Plant;
- USGS 50093083 discharge above the AES intake;
- the exact AguaYLuz utility-asset slice from pinned main.

The manifest hashes the committed canonical extracts, not full upstream HTTP response bodies. Every USGS value is preserved as provisional. Gate-opening records remain operational context and are not converted to discharge.

## Real-baseline adjudication

The observed baseline intentionally resolves to `insufficient_data`:

1. Reservoir elevation is not reservoir volume.
2. A single elevation does not establish storage change.
3. Above- and below-treatment observations are separated by approximately ten days.
4. The forebay and downstream-intake observations are older still.
5. Direct treatment withdrawal and terminal flow are absent.
6. No validated evaporation, seepage, canal-loss, or treatment-loss model exists.

Therefore every real observation remains `context`, and the shared engine receives zero balance-eligible observations. No residual or root-cause claim is produced.

## Legacy-path equivalence

PR #118 contains a domain-specific synchronized canal balance:

```text
residual = canal_release
         - treatment_withdrawal
         - agricultural_turnout
         - terminal_flow
         - known_leak_flow
```

The pilot maps the same terms to the shared core:

| PR #118 term | Shared role |
|---|---|
| `canal_release` | `inflow` |
| `treatment_withdrawal` | `outflow` |
| `agricultural_turnout` | `outflow` |
| `terminal_flow` | `outflow` |
| `known_leak_flow` | `documented_loss` |

Synthetic fixtures prove exact residual equivalence for balanced, within-tolerance, positive-residual, and negative-residual cases. Status names differ intentionally:

- `balanced_within_tolerance` maps to `balanced` or `within_uncertainty`;
- `unexplained_positive_residual` maps to `unaccounted_deficit`;
- `contradictory_negative_residual` maps to `unaccounted_surplus`.

Both implementations leave root cause unresolved.

## Regression fixture set

The fixture suite covers:

- positive balanced control;
- exact balance;
- within uncertainty;
- unaccounted deficit;
- unaccounted surplus;
- missing required observation;
- stale observation window;
- mixed units;
- topology cycle;
- sensor-bias correction as an inference requiring calibration evidence.

Synthetic fixtures are labeled `synthetic_regression`. They are not observations of Patillas, Guayama, AAA, PREPA, or AES operations.

## Hierarchical boundaries

The frozen topology defines a design-only sequence:

```text
Patillas watershed
  → Lago Patillas reservoir
  → Guayama treatment boundary
  → downstream distribution and intake boundary
```

The sequence is inferred from source-declared station names. It is not authoritative hydraulic topology and contains no valve, pipe, pressure-zone, or control-state claims.

## Rollback and containment

Rollback is deletion of the additive pilot module, fixtures, tests, and documentation. No existing schema, model, API, GUI, export, alert, scheduler, data file, or federation contract is modified.

Runtime promotion remains blocked until:

- PR overlap is re-adjudicated after any merge or head movement;
- authoritative topology identifiers are available;
- synchronized volumetric observations exist;
- stage-storage conversion and expected-loss models are validated;
- historical equivalence is demonstrated on real complete windows;
- a separate runtime-promotion ballot is approved;
- exact-head CI is terminal green.
