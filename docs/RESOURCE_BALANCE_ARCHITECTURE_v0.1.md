# Shared Resource Balance and Loss Attribution Architecture v0.1

**Status:** Design-only reference core  
**Pinned implementation base:** `main@17c843595b5cdfbcef4e5f7b1ac6c662092e335d`  
**Runtime state:** inactive; no API, GUI, export, alert, notification, scheduler, or data migration

## Decision

AguaYLuz already owns both water and power infrastructure, monitoring, incidents, alerts, review, GUI diagnostics, and federation export. The redesign therefore adds one shared accounting vocabulary rather than a parallel electrical application. Water and electricity share boundary, interval, topology, provenance, uncertainty, residual, and investigation mechanics. Domain physics remain separate.

Canonical balance:

```text
residual = gross_input - gross_output - storage_change - documented_loss - expected_loss
```

A residual above the combined uncertainty envelope is an **accounting discrepancy**. It is not proof of theft, fraud, illegal diversion, unauthorized use, or an exact failure location.

## Versioned contracts

The schema bundle defines thirteen contracts:

1. `ResourceAsset`
2. `ResourceFlowEdge`
3. `ResourceObservation`
4. `StorageState`
5. `ConversionProcess`
6. `BalanceBoundary`
7. `BalanceWindow`
8. `ExpectedLossModel`
9. `UncertaintyEnvelope`
10. `ResidualAttribution`
11. `BalanceResult`
12. `TopologyState`
13. `InvestigationCase`

## Compatibility matrix

| Existing component | Classification | Reuse path | Constraint |
|---|---|---|---|
| `utility_asset.schema.json` / `UtilityAsset` | WRAP | `ResourceAsset` preserves the legacy identifier and provenance | No source-row rewrite |
| `monitoring_reading.schema.json` | EXTEND | Adapter preserves value, unit, date, source, tier, confidence, review | Legacy readings remain context-only until direction, interval and uncertainty are explicit |
| `service_event.schema.json` | REUSE_UNCHANGED | Corroboration and known-event validation | Not a flow ledger |
| `alert_event.schema.json` and alert modules | REUSE_UNCHANGED | Later residual promotion after policy ballot | No alert activation in v0.1 |
| monitoring freshness/quality | GENERALIZE | Eligibility gate for balance observations | Stale or proxy readings cannot silently become current direct evidence |
| monitoring incident ledger | REUSE_UNCHANGED | Investigation history and append-only transitions | Residual is not an incident by itself |
| water-disruption shadow consumer | DOMAIN_SPECIFIC | Water operational context and known disruptions | Do not duplicate its intake or lifecycle |
| utility asset graph / PR #101 | EXTERNAL_OVERLAP | Future topology source after adjudication | This branch does not copy or depend on unmerged code |
| Laguna Cartagena control plane / PR #118 | EXTERNAL_OVERLAP | Future synchronized water-balance pilot | No fabricated operator observations |
| USGS category coverage / PR #116 | EXTERNAL_OVERLAP | Future observation suppliers | Provider registration does not equal usable balance coverage |
| `water_alerts.py` statistical tails | LEGACY_ANALYTIC | Corroborating context only | Tail anomaly is not a mass balance |
| `impact.py` dependency linkage | GENERALIZE | Candidate boundary/asset association | Proximity cannot establish physical flow |
| federation exporter | EXTEND_LATER | Export validated balances after hub contract approval | No export change in v0.1 |
| dashboard monitoring/analytics pages | EXTEND_LATER | Read-only balance control plane | No route or component change in v0.1 |
| review queue | REUSE_UNCHANGED | Human adjudication of inferred causes | No automatic confirmation |
| GUI capability parity ratchet | REUSE_UNCHANGED | Promotion gate | Reference code stays outside runtime discovery roots |
| G01–G08 validation gates | REUSE_UNCHANGED | Repository-wide certification | Focused tests do not replace full CI |
| source manifest and evidence tiers | REUSE_UNCHANGED | Provenance binding | T1–T4 meaning is preserved |
| asset crosswalk | GENERALIZE | Alias and duplicate resolution | Crosswalk does not prove topology |
| scheduled refresh | EXTEND_LATER | Materialize synchronized inputs | No new cadence in v0.1 |

## Domain extensions

### Water

Rainfall-runoff and recharge, watershed lag, reservoir elevation-volume curves, evaporation, seepage, treatment-process use, well pumping, tank storage, pressure-zone flow, and hydraulic topology remain water-specific.

### Electricity

Gross/net generation, plant auxiliary load, real and reactive power, transformer and conductor losses, voltage and phase state, storage charge/discharge, distributed solar, net metering, feeder switching, AMI, and transformer-to-service connectivity remain electricity-specific.

## Reference behavior

The design-only Python core:

- wraps existing assets without mutation;
- converts existing readings to ineligible context records unless missing semantics are supplied;
- requires a single resource domain and canonical unit per balance;
- binds every result to a boundary, time window, and topology state;
- combines measurement and expected-loss uncertainty by root-sum-square;
- separates facts from inferences;
- defaults attribution to `unresolved`;
- produces deterministic content-derived identifiers.

## Promotion gates

Runtime promotion requires all of the following:

1. exact-current-main reconciliation and overlap adjudication with open PRs;
2. frozen water fixtures proving zero semantic and numeric drift;
3. authoritative or explicitly qualified topology states;
4. synchronized interval observations with units, direction, and uncertainty;
5. domain-engineering review of water and electrical expected-loss models;
6. API, GUI, accessibility, and end-to-end parity evidence;
7. federation contract approval before export;
8. rollback and historical reproducibility evidence;
9. full CI and security workflows on the exact final head;
10. a separate activation ballot.

## Known gaps

- No authoritative AAA hydraulic topology, valve state, tank telemetry, treatment withdrawal, or synchronized pressure-zone flow is present on pinned main.
- No complete LUMA/PREPA substation-feeder-transformer-service topology, interval AMI corpus, or distributed-energy ledger is present on pinned main.
- Existing daily monitoring rows generally lack direction, interval boundaries, and defensible uncertainty.
- Technical loss models and hydrologic loss models must be versioned and independently validated.
- Two opposing measurement biases can cancel and falsely close a balance; cross-sensor contradiction review remains mandatory.
