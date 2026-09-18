from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


finalizer = _load("finalize_federation_outputs", "scripts/finalize_federation_outputs.py")
freezer = _load("freeze_federation_runtime", "scripts/freeze_federation_runtime.py")


def test_strict_runtime_aggregate_never_treats_skip_as_pass():
    assert finalizer._strict_aggregate(["PASS", "PASS"]) == "PASS"
    assert finalizer._strict_aggregate(["PASS", "WARN"]) == "WARN"
    assert finalizer._strict_aggregate(["PASS", "SKIP"]) == "BLOCKED"
    assert finalizer._strict_aggregate(["PASS", "SKIP", "FAIL"]) == "FAIL"


def test_freezer_fails_closed_when_runtime_files_are_missing(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    monkeypatch.setattr(freezer, "OUTPUTS", outputs)
    monkeypatch.setattr(freezer, "FEDERATION", outputs / "federation")
    monkeypatch.setattr(freezer, "_git", lambda *args: "a" * 40 if "HEAD^{tree}" not in args else "b" * 40)
    result = freezer.freeze(tmp_path / "missing-receipt.json", evidence_only=True)
    assert result["ok"] is False
    assert result["certification_eligible"] is False
    assert any("missing operator outputs" in problem for problem in result["problems"])
    assert any("missing canonical federation manifest" in problem for problem in result["problems"])
