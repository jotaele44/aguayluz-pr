# aguayluz-pr

**Puerto Rico water / power / utility infrastructure intelligence producer for the
PRII Federation control plane.**

`aguayluz-pr` is a federation *producer* (role: `water_grid_monitoring_node`,
hub parent: [`thehub-pr`](https://github.com/jotaele44/thehub-pr)). It ingests
public water, power, and utility-infrastructure data for Puerto Rico — EPA WATERS /
NHDPlus hydrology, generation and substation/transmission assets, treatment and
wastewater facilities, and outage/service events — and publishes a canonical,
reviewable export package that the hub aggregates alongside the other producers.

## Federation role

| | |
|---|---|
| Program id | `aguayluz-pr` |
| Federation role | `water_grid_monitoring_node` |
| Hub parent | `thehub-pr` |
| Canonical export | `exports/federation/` (via `scripts/federation_export.py`) |

Canonical outputs (see `federation.json`): `outputs/base44_export.json`,
`outputs/integration_report.json`, `outputs/source_manifest.json`,
`outputs/review_queue.json`, and `reports/maintenance/latest.json`.

## Repository layout

| Path | Purpose |
|---|---|
| `src/aguayluz/` | Package + `aguayluz` CLI (waters client, models, alerts, maintenance) |
| `scripts/` | Ingest/build/export scripts (POWER, PREPS, AEE/LUMA, geo boundaries, federation export) |
| `server/` | FastAPI backend that serves the dashboard data API |
| `dashboard/` | Frontend (npm-built) |
| `desktop/` | Double-click desktop wrapper (see `desktop/README.md`) |
| `schemas/`, `registry/`, `config/` | Manifest schemas, source registry, config |
| `data/`, `outputs/`, `exports/`, `reports/` | Inputs and generated artifacts |
| `tests/` | Pytest suite |

## Setup / Development

Requires **Python 3.10+** (CI tests 3.10 and 3.12).

```bash
git clone https://github.com/jotaele44/aguayluz-pr.git
cd aguayluz-pr
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]          # runtime + lint/test tooling (matches federation.json `setup`)
```

Run the quality gates locally — these are the same checks `validate.yml` runs in CI:

```bash
ruff check .                      # lint
pytest -q                         # tests
python scripts/validate_repo.py   # federation validation gates
```

The heavy geospatial stack (GDAL-backed `geopandas`) is only needed by
`scripts/build_pr_geo_boundaries.py` and is kept out of the default install:

```bash
pip install -e .[geo]          # only if you run the geo boundary builder
```

The backend that serves the dashboard data API uses `server/backend/requirements.txt`;
CI installs it before running the suite:

```bash
pip install -r server/backend/requirements.txt
```

### Desktop app

To run AGUAYLUZ as a native double-click app (bundled dashboard + local API), see
[`desktop/README.md`](desktop/README.md). Quick version:

```bash
python desktop/setup.py                     # one-time setup (needs internet + Node.js once)
.venv/bin/python desktop/launch.py          # native window
```

## Federation commands

The hub invokes these via `federation.json` → `hub_callable_commands`:

```bash
python -m pip install -e .[dev]                       # setup
python scripts/validate_repo.py                       # validation_gates
python -m pytest -q                                   # test_suite
python3 scripts/federation_export.py --mode test      # export_canonical
aguayluz maintenance --mode audit                     # maintenance
```

Ingest/build commands (POWER, PREPS, LUMA/AEE outages, municipio & boundary geometry)
are also declared in `federation.json`; several require operator-supplied source
files or hit ToS-gated live APIs — see each script's header.

## License

MIT — see [`LICENSE`](LICENSE).
