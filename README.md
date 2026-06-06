# aguayluz-pr

Puerto Rico public water, wastewater, power, grid, outage, and recovery-project
intelligence producer for the Federation control plane (Base44 / INTSYS-PR /
thehub-pr). Maps PRASA / AAA / LUMA / Genera public records to EPA NHDPlus V2.1
reaches via the U.S. EPA Office of Water [WATERS Services REST API][waters].

> AguaYLuz does not allege wrongdoing. It maps systems, dependencies, service
> gaps, project status, and evidence-backed infrastructure relationships.

**Status:** scaffold (M1) — schemas + validation gates + tests. WATERS HTTP
client lands in M2, navigation/mapping in M3, Base44 exporter + smoke test in
M4. See [skill spec](./AGUAYLUZ_PR_SKILL.md) (delivered out-of-band) and the
build plan at `~/.claude/plans/u-s-epa-office-of-pure-newell.md`.

## Install

```
python -m pip install -e .[dev]
```

Python 3.10+ required (works on iOS a-Shell).

## Run the validation gates

```
python scripts/validate_repo.py
```

Eight gates (G01-G08) per the skill spec. Exits non-zero on any blocking failure.

## Run tests

```
pytest -q
```

## EPA WATERS API key

Get a free key at [api.data.gov/signup][signup] (one key works across all
api.data.gov-fronted services). Then:

```
export EPA_WATERS_API_KEY=<your-key>
```

The client falls back to `API_DATA_GOV_KEY` if `EPA_WATERS_API_KEY` is not set.
Free tier is 1,000 requests/hour (rolling).

## Puerto Rico caveat — NHDPlus V2.1 VPU 21

PR is covered as VPU 21, but the `VogelExtension`, `VPUAttributeExtension`, and
`VPUAttributeExtensionNLCD` datasets are **not available** for VPU 21. Records
sourced from PR are stamped `attribute_coverage: "partial"` rather than
silently filled (skill spec rule 8 — no silent substitution).

## Repo layout

```
schemas/         JSON Schema (Draft 2020-12) for utility_asset, service_event,
                 aguayluz_bridge_summary, base44_export, source_manifest,
                 review_queue, integration_report.
src/aguayluz/    Pydantic models, validation gates, confidence scorer,
                 (M2+) waters/ HTTP client and pynhd navigation.
scripts/         CLI entry points runnable from a-Shell.
config/          module.yaml, federation_manifest.yaml, validation_gates.yaml.
tests/           pytest suite (schemas, validation, fixtures).
```

## License

MIT — see [LICENSE](./LICENSE).

[waters]: https://watersgeo.epa.gov/openapi/waters/
[signup]: https://api.data.gov/signup/
