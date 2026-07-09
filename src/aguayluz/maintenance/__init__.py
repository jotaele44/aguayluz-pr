"""Repo-specific maintenance adapter for aguayluz-pr.

The generic maintenance core (models/state/detect/corrections/quarantine/report/
runner) now lives in the shared `prii_maintenance` package
(thehub-pr/packages/prii_maintenance, pinned in pyproject.toml). Only
`adapters/local.py` — the aguayluz-specific checks — stays vendored here; it is
passed into `prii_maintenance.run_maintenance(..., local_checks=local.run_checks)`
by the `aguayluz maintenance` CLI command.
"""
