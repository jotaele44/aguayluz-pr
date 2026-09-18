# Mycelial Plan Max W00/W02/W07 addendum v1

Status: **DRAFT / DESIGN ONLY**

This addendum extends and, where counts differ, supersedes the package inventory in `MYCELIAL_PLANMAX_W00_W02_W07_EXECUTION_V1.md`.

## Target-identity hardening

The W07 design now contains **four**, not three, Draft 2020-12 field schemas:

1. `schemas/mycelial-field/v1/study-target.schema.json`
2. `schemas/mycelial-field/v1/field-site.schema.json`
3. `schemas/mycelial-field/v1/field-survey.schema.json`
4. `schemas/mycelial-field/v1/fruiting-observation.schema.json`

`study-target.schema.json` prevents the semantic meaning of a target from drifting between field collection and later analytical work. It preserves target kind, taxonomic/definition scope, inclusion and exclusion rules, minimum verification class, sensitivity, forecast role, and review state.

A sensitive or sensitivity-unresolved target cannot be designated a future forecast candidate under this contract.

## Field worksheet

`docs/mycelial/field_protocol/KNOWN_SITE_FIELD_WORKSHEET_V1.md` is a human-readable capture template aligned to the schema package. It intentionally contains no exact-coordinate field and is not itself a biological record until completed, reviewed, and admitted through a separately authorized evidence path.

## Additional synthetic fixtures

`tests/fixtures/mycelial_field_protocol/v1/targets.json` contains synthetic target-only fixtures. It is prohibited from biological-data or model-training admission.

`tests/test_mycelial_field_protocol_design_v1.py` has been updated to include the study-target schema and fixtures.

## Certification state

The latest GitHub workflow wave for this branch currently reports failures without executed job steps. Direct clone from the independent execution environment also failed at DNS before checkout. Therefore this package remains **PROVISIONAL / EXECUTION BLOCKED**. Neither schema validity nor repository regression PASS is claimed from workflow status alone.

No biological records were acquired or inserted by this addendum. No model, API, GUI, scheduler, notification, coordinate disclosure, habitat suitability, connectivity, growth rate, or prediction capability was opened.
