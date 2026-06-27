# aguayluz-pr — Water / Grid Monitoring Producer (PRII federation)

`aguayluz-pr` is the Puerto Rico water, wastewater, power, grid, outage, and recovery-project intelligence producer for the Puerto Rico Integrated Intelligence (PRII) federation.

It maps PRASA / AAA, LUMA, Genera, PREPA, emergency-portal, public infrastructure, and geospatial records into reviewable utility assets, service events, source manifests, and canonical federation exports for [`thehub-pr`](https://github.com/jotaele44/thehub-pr).

> AguaYLuz does not allege wrongdoing. It maps systems, dependencies, service gaps, project status, and evidence-backed infrastructure relationships.

## Current operating state

| Field | Value |
|---|---|
| Program id | `aguayluz-pr` |
| Federation role | `water_grid_monitoring_node` |
| Parent hub | [`thehub-pr`](https://github.com/jotaele44/thehub-pr) |
| Production status | `PRODUCTION_REAL_DATA_PARTIAL` |
| Live execution gate | Ready for Hub live execution, subject to local source/key availability |

The repository has moved beyond scaffold-only status. Current federation metadata identifies real-data partial operation, with loaded power and water/wastewater assets plus service-event/outage inputs that retain coverage caveats and review status.

## Scope

| Domain | Ownership |
|---|---|
| Water and wastewater assets | PRASA / AAA and related public references |
| Power and grid assets | PREPA / LUMA / Genera public records, generation, substations, feeders, poles, transmission, distribution |
| Service interruptions | Outages, restoration, service events, emergency-portal records |
| Recovery projects | Utility recovery project status and spatial summaries |
| Geospatial joins | Puerto Rico municipios, barrios, and NHDPlus V2.1 / VPU 21 references |

## Data-source caveats

Puerto Rico is covered as NHDPlus V2.1 VPU 21, but `VogelExtension`, `VPUAttributeExtension`, and `VPUAttributeExtensionNLCD` are unavailable for VPU 21. Puerto Rico records are stamped with partial attribute coverage rather than silently substituted.

Some outage inputs are point-in-time or third-party snapshots. Treat those as review-grade until a direct recurring source is wired and promoted.

## Install

```bash
python -m pip install -e .[dev]
```

Python 3.10+ required.

## Run gates

```bash
python scripts/validate_repo.py
pytest -q
ruff check .
```

## Federation commands

```bash
python3 scripts/federation_export.py --mode test
python3 scripts/ingest_power.py
python3 scripts/ingest_preps.py
python3 scripts/ingest_aee.py --src <outages_by_town.json> --snapshot-ts <commit_iso8601>
python3 scripts/build_pr_municipios_geo.py --src <census_gazetteer_counties.txt>
```

## Operational alert system

A permanent multi-sector operational-alert framework (10 modules; 5 active) with
its own JSON schema, SQLite/PostGIS DDL, validation pipeline (VAL-001..010),
dependency graph, gap log, and Claude MCP tool contract. Alerts project into the
federation `alerts` stream consumed by [`thehub-pr`](https://github.com/jotaele44/thehub-pr).
See [docs/ALERT_SYSTEM.md](./docs/ALERT_SYSTEM.md).

```bash
python3 scripts/build_alert_system.py    # build SQLite from DDL + seeds, run VAL rules, emit GeoJSON
aguayluz alerts validate                 # run VAL-001..010 over the seed alerts
```

## EPA WATERS API key

```bash
export EPA_WATERS_API_KEY=<your-key>
```

The client falls back to `API_DATA_GOV_KEY` if `EPA_WATERS_API_KEY` is not set.

## Repo layout

```text
schemas/         JSON Schema files for utility assets, service events, alerts, exports, manifests, queues, and reports
schemas/sql/     SQLite/PostGIS-ready DDL (alert system)
src/aguayluz/    Pydantic models, validators, confidence scoring, alert system, WATERS/client logic
scripts/         CLI entry points and ingest/export/build commands
config/          module, validation, alert-module, and MCP-tool configuration
docs/            subsystem documentation (alert system)
tests/           pytest suite
outputs/         generated local outputs; do not promote without gate review
exports/         federation export packages
```

## License

MIT — see [LICENSE](./LICENSE).
