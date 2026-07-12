"""Shared-package wiring smoke test for aguayluz-pr's maintenance CLI command.

Generic detection/runner behavior now lives in thehub-pr's shared
`prii_maintenance` package (thehub-pr/packages/prii_maintenance/tests/); this
just proves the `aguayluz maintenance` command's dependency-injection wiring
(`prii_maintenance.run_maintenance(..., local_checks=local.run_checks)`)
actually reaches this repo's adapter.
"""

from __future__ import annotations

import json

from prii_maintenance import run_maintenance

from aguayluz.maintenance.adapters import local


def test_run_maintenance_invokes_local_adapter(tmp_path, monkeypatch):
    monkeypatch.delenv("EPA_WATERS_API_KEY", raising=False)
    fed = {
        "program_id": "aguayluz-pr",
        "source_truth": {"runtime_required_keys": ["EPA_WATERS_API_KEY"]},
        "canonical_outputs": {},
    }
    (tmp_path / "federation.json").write_text(json.dumps(fed), encoding="utf-8")
    report = run_maintenance(
        root=tmp_path,
        mode="audit",
        write=False,
        program_id="aguayluz-pr",
        local_checks=local.run_checks,
    )
    assert any(
        f.category == "dependency_drift" and f.severity == "warning"
        for f in report.findings
    )
