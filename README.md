# AguaYLuz — Puerto Rico Water & Power Infrastructure Producer (PRII federation)

`AguaYLuz` is the water/wastewater/power/outage monitoring node of the Puerto
Rico Integrated Intelligence (PRII) federation.

Its federation alias is `aguayluz-pr`. It owns water and wastewater assets,
power generation/grid infrastructure, outage and service-interruption events,
and utility geospatial summaries, exporting them as canonical streams for
downstream correlation in [`thehub-pr`](https://github.com/jotaele44/thehub-pr).

> **Diagnostic-only surface (ADR 0001, Phase 2).** This repo's dashboard is a
> development and diagnostic tool for this producer only. The supported product
> surface for the PRII federation is the hub app
> (`thehub-pr/server/frontend`), which renders this producer's data alongside
> the other engines. See `thehub-pr/docs/adr/0001-federated-engines-single-hub.md`.

## Federation role

| Field | Value |
|---|---|
| Repository | `jotaele44/aguayluz-pr` |
| Federation alias | `aguayluz-pr` |
| Parent hub | [`thehub-pr`](https://github.com/jotaele44/thehub-pr) |
| Primary function | Water/wastewater/power asset registry, outage and service-event monitoring |
| Jurisdiction focus | Puerto Rico |
| Upstream signal source | `centinelas-pr` (news/regulatory signals via `scripts/ingest_news_event.py`) |

## Real-data status

Production status is `PRODUCTION_REAL_DATA_PARTIAL` (`federation.json`): the
corpus is real public data, with some sources external or point-in-time.

- 273 utility assets from public ingests — 39 power generation/substation/
  transmission nodes (`scripts/ingest_power.py`, EIA-860 + OSM derived) and 234
  OSM-derived water/wastewater treatment/pumping/reservoir nodes
  (`scripts/ingest_water.py`, `review_status=needs_review`). Locally imported
  historical hydro registers (`scripts/import_local_hydro_assets.py`) grow
  `data/utility_assets.jsonl` beyond that core.
- PREPS island-wide service events (`scripts/ingest_preps.py`) plus
  per-municipio AEE/LUMA outage incidents (`scripts/ingest_aee.py`, tier
  T2/needs_review point-in-time snapshot).
- Operational alert events (`docs/ALERT_SYSTEM.md`) and the 78-municipio /
  901-barrio geo layer under `data/geo/` (U.S. Census cartographic boundaries).

Advisory/provenance notes live in
`federation.json#federation_readiness_gate.resolved_conditions`; both readiness
booleans are `true` and `blocking_conditions` is empty.

## Run

Commands as declared in `federation.json#hub_callable_commands`:

```bash
[ -d ../thehub-pr ] || git clone https://github.com/jotaele44/thehub-pr.git ../thehub-pr  # shared prii-* libs live here
python -m pip install uv && uv pip install -e .[dev]   # setup (uv reads [tool.uv.sources])
python -m pytest -q                          # test_suite
python scripts/validate_repo.py              # validation gates G01-G08
python3 scripts/federation_export.py --mode test   # export_canonical
```

## Desktop app

Double-click launchers at the repo root start the local desktop app (first run
installs dependencies, later runs work offline):

- `PRII-AGUAYLUZ.command` (macOS) / `PRII-AGUAYLUZ.app`
- `PRII-AGUAYLUZ.bat` (Windows)
- `PRII-AGUAYLUZ.sh` (Linux)

## Federation contract

`federation.json` is this producer's manifest, conformant to
`thehub-pr/schemas/repo_federation_manifest.schema.json`.
`scripts/federation_export.py` writes
`exports/federation/{sources,entities,relationships,alerts}.jsonl` plus a
`manifest.json` validated against the vendored hub schema
`schemas/federation_export_manifest.schema.json`
(`tests/test_federation_contract_compat.py`).
