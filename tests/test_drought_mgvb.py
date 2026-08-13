# ruff: noqa: I001
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from research.drought_resilience.mgvb.certify_usdm import certify
from research.drought_resilience.mgvb.replay_freeze import replay
from research.drought_resilience.mgvb.usdm_freeze import expected_issue_dates, freeze


BUILDPLAN = Path("research/drought_resilience/mgvb_buildplan.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_required_script_census_is_frozen_and_present():
    plan = json.loads(BUILDPLAN.read_text(encoding="utf-8"))
    required = [item for item in plan["script_census"] if item["class"] == "required"]
    assert [item["id"] for item in required] == ["S01", "S02", "S03", "S04", "S05", "S06"]
    for item in required:
        path = Path(item["path"])
        assert path.is_file()
        assert _sha(path) == item["sha256"]


def test_dependency_dag_is_acyclic():
    plan = json.loads(BUILDPLAN.read_text(encoding="utf-8"))
    graph = {item["id"]: set(item.get("depends_on", [])) for item in plan["script_census"]}
    pending = {node: set(deps) for node, deps in graph.items()}
    resolved: set[str] = set()
    while pending:
        ready = sorted(node for node, deps in pending.items() if deps <= resolved)
        assert ready, f"dependency cycle/unresolved dependency: {pending}"
        for node in ready:
            resolved.add(node)
            pending.pop(node)
    assert len(resolved) == len(graph)


def _write_annual_archives(root: Path) -> None:
    for year in (2014, 2015, 2016):
        path = root / f"{year}_USDM_GML.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for issue in expected_issue_dates():
                if issue.year != year:
                    continue
                stamp = issue.strftime("%Y%m%d")
                archive.writestr(f"USDM_{stamp}_M/USDM_{stamp}.gml", "<gml/>")


def test_mgvb_offline_freeze_certify_and_replay(tmp_path: Path):
    offline = tmp_path / "offline"
    offline.mkdir()
    _write_annual_archives(offline)
    evidence = tmp_path / "evidence"
    manifest_path, manifest_sha = freeze(evidence, offline_input_dir=offline)
    result = certify(manifest_path)
    assert result == {
        "source_family": "USDM",
        "annual_objects": 3,
        "week_count": 156,
        "missing": 0,
        "unexpected": 0,
        "status": "certified",
    }
    replay_result = replay(manifest_path, manifest_sha)
    assert replay_result["status"] == "replay_pass"
    assert replay_result["network_required"] is False
