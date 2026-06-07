# aguayluz-pr

Puerto Rico public water, wastewater, power, grid, outage, and recovery-project
intelligence producer for the Federation control plane (Base44 / INTSYS-PR /
thehub-pr). Ingests EPA FRS, FEMA OpenFEMA, and HIFLD; snaps every record to
NHDPlus V2.1 via the EPA WATERS API; emits a sanitized Base44 envelope plus
per-receiver federation handoff payloads.

> AguaYLuz does not allege wrongdoing. It maps systems, dependencies, service
> gaps, project status, and evidence-backed infrastructure relationships.

## Install + run

```
python -m pip install -e .[dev]
python scripts/validate_repo.py
pytest -q
```

Python 3.10+ required (works on iOS a-Shell).

## Try a full run (demo mode, no API key needed)

```
aguayluz ingest-frs --input tests/fixtures/frs/pr_bayamon_npdes.json --demo-mode
aguayluz ingest-fema --input tests/fixtures/fema/pr_public_assistance_sample.json
aguayluz build-graph --demo-mode
aguayluz reconcile
aguayluz delineate --demo-mode
aguayluz emit-handoffs
aguayluz snapshot --slug demo-run
aguayluz validate-repo
```

After the run, `outputs/base44_export.json` is the federation envelope and
`outputs/handoff_*.json` are the per-receiver payloads.

## Live mode

EPA WATERS needs a free api.data.gov key:

```
export EPA_WATERS_API_KEY=<your-key>     # https://api.data.gov/signup/
aguayluz ingest-frs --live --state PR --city BAYAMON --demo-mode
aguayluz ingest-fema --live --state PR --damage-codes D,F --max-records 50
aguayluz delineate --max-calls 10
```

FRS, FEMA, and HIFLD don't need a key.

## Puerto Rico caveat — NHDPlus V2.1 VPU 21

PR is covered as VPU 21, but `VogelExtension`, `VPUAttributeExtension`, and
`VPUAttributeExtensionNLCD` are **not available** for VPU 21. Records sourced
from PR are stamped `attribute_coverage: "partial"` rather than silently
filled (skill spec rule 8 — no silent substitution).

## Docs

- [`docs/architecture.md`](./docs/architecture.md) — layers, schemas, vectors, entity flow.
- [`docs/vectors.md`](./docs/vectors.md) — input/output per execution vector + CLI usage.
- [`docs/schemas.md`](./docs/schemas.md) — one paragraph per JSON Schema.
- [`docs/contributing.md`](./docs/contributing.md) — how to add an adapter / analyzer / schema.
- [`docs/upstream-changes.md`](./docs/upstream-changes.md) — drift detection + acceptance runbook.
- [`AGUAYLUZ_PR_SKILL.md`](./AGUAYLUZ_PR_SKILL.md) — the federation contract this module satisfies.

## License

MIT — see [LICENSE](./LICENSE).
