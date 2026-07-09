"""AguaYLuz maintenance adapter checks."""

from __future__ import annotations

import json

from prii_maintenance import state as state_mod

from aguayluz.maintenance.adapters import local


def _scaffold(root, *, assets=None, events=None, keys=("EPA_WATERS_API_KEY",)):
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    fed = {
        "program_id": "aguayluz-pr",
        "source_truth": {"runtime_required_keys": list(keys)},
        "canonical_outputs": {},
    }
    (root / "federation.json").write_text(json.dumps(fed), encoding="utf-8")
    if assets is not None:
        (root / "outputs" / "utility_assets.json").write_text(json.dumps(assets), encoding="utf-8")
    if events is not None:
        (root / "outputs" / "service_events.json").write_text(json.dumps(events), encoding="utf-8")
    return state_mod.collect_repo_state(root)


def test_run_checks_returns_finding_list(tmp_path, monkeypatch):
    monkeypatch.delenv("EPA_WATERS_API_KEY", raising=False)
    state = _scaffold(tmp_path)
    findings = local.run_checks("aguayluz-pr", tmp_path, state)
    assert isinstance(findings, list)
    assert all(f.repo == "aguayluz-pr" for f in findings)


def test_api_key_absent_is_warning(tmp_path, monkeypatch):
    monkeypatch.delenv("EPA_WATERS_API_KEY", raising=False)
    state = _scaffold(tmp_path)
    findings = local.check_api_health_config("aguayluz-pr", tmp_path, state)
    assert any(f.category == "dependency_drift" and f.severity == "warning" for f in findings)


def test_api_key_present_no_finding(tmp_path, monkeypatch):
    monkeypatch.setenv("EPA_WATERS_API_KEY", "x" * 20)
    state = _scaffold(tmp_path)
    assert local.check_api_health_config("aguayluz-pr", tmp_path, state) == []


def test_asset_missing_source_ref_is_error(tmp_path):
    state = _scaffold(tmp_path, assets=[{"asset_id": "A1"}])  # no source_ref
    findings = local.check_asset_lineage("aguayluz-pr", tmp_path, state)
    assert len(findings) == 1
    assert findings[0].category == "lineage"
    assert findings[0].severity == "error"
    assert findings[0].action == "quarantined"


def test_asset_with_source_ref_passes(tmp_path):
    state = _scaffold(tmp_path, assets=[{"asset_id": "A1", "source_ref": "epa://x"}])
    assert local.check_asset_lineage("aguayluz-pr", tmp_path, state) == []


def test_orphan_relationship_is_error(tmp_path):
    state = _scaffold(
        tmp_path,
        assets=[{"asset_id": "A1", "source_ref": "epa://x"}],
        events=[{"event_id": "E1", "linked_asset_ids": ["A1", "GHOST"]}],
    )
    findings = local.check_orphan_relationships("aguayluz-pr", tmp_path, state)
    assert len(findings) == 1
    assert "GHOST" in findings[0].message
    assert findings[0].severity == "error"
