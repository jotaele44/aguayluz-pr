from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from aguayluz.validation import GateReport, GateResult

ROOT = Path(__file__).resolve().parents[1]


def _load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


spatial_validator = _load_script("validate_federation_spatial", "scripts/validate_federation_spatial.py")
repo_validator = _load_script("validate_repo", "scripts/validate_repo.py")


def _spatial_manifest() -> dict:
    return json.loads((ROOT / "federation.spatial.json").read_text(encoding="utf-8"))


def test_spatial_audit_accepts_structurally_valid_open_manifest():
    manifest = _spatial_manifest()
    assert spatial_validator.validate_manifest(manifest, certification=False) == []


def test_spatial_certification_rejects_every_non_pass_gate():
    manifest = _spatial_manifest()
    problems = spatial_validator.validate_manifest(manifest, certification=True)
    for gate, state in manifest["gates"].items():
        assert state != "PASS"
        assert any(f"certification gate {gate} is {state}" in problem for problem in problems)


def test_spatial_certification_accepts_same_manifest_when_all_required_gates_pass():
    manifest = _spatial_manifest()
    manifest["gates"] = {
        gate: "PASS" for gate in spatial_validator.REQUIRED_CERTIFICATION_GATES
    }
    assert spatial_validator.validate_manifest(manifest, certification=True) == []


def test_spatial_certification_rejects_missing_and_unknown_gate_states():
    manifest = _spatial_manifest()
    manifest["gates"] = {
        gate: "PASS" for gate in spatial_validator.REQUIRED_CERTIFICATION_GATES
    }
    manifest["gates"].pop("security")
    manifest["gates"]["performance"] = "MAGIC"
    problems = spatial_validator.validate_manifest(manifest, certification=True)
    assert any("missing certification gates" in problem for problem in problems)
    assert any("invalid gate state performance='MAGIC'" in problem for problem in problems)


def test_repo_audit_preserves_skip_but_certification_rejects_it():
    report = GateReport(
        results=[
            GateResult("G01_SCHEMA", "PASS", "ok"),
            GateResult("G02_SOURCE_MANIFEST", "SKIP", "missing runtime output"),
        ]
    )
    audit = repo_validator._payload(report, certification=False)
    certification = repo_validator._payload(report, certification=True)
    assert audit["status"] == "PASS"
    assert audit["blocking_failure_count"] == 0
    assert certification["status"] == "FAIL"
    assert certification["blocking_failure_count"] == 1


def test_executed_test_receipt_must_bind_current_commit_and_tree(tmp_path, monkeypatch):
    commit = "a" * 40
    tree = "b" * 40
    monkeypatch.setattr(repo_validator, "_current_git_identity", lambda: (commit, tree))
    path = tmp_path / "receipt.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": repo_validator.TEST_RECEIPT_SCHEMA,
                "repository": "jotaele44/aguayluz-pr",
                "commit_sha": commit,
                "tree_sha": tree,
                "status": "PASS",
                "suite": "FULL",
                "command": "pytest -q --cov",
            }
        ),
        encoding="utf-8",
    )
    assert repo_validator._validate_test_receipt(path)["status"] == "PASS"

    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["commit_sha"] = "c" * 40
    path.write_text(json.dumps(receipt), encoding="utf-8")
    result = repo_validator._validate_test_receipt(path)
    assert result["status"] == "FAIL"
    assert "commit_sha" in result["details"]
