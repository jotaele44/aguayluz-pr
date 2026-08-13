# ruff: noqa: I001
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import date
from pathlib import Path

from research.drought_resilience.mgvb.certify_usdm import certify
from research.drought_resilience.mgvb.replay_freeze import replay
from research.drought_resilience.mgvb.usdm_freeze import (
    KNOWN_NON_ISSUE_DATES,
    expected_issue_dates,
    freeze,
)


BUILDPLAN = Path("research/drought_resilience/mgvb_buildplan.json")
SUPPLEMENTAL_2015 = [
    "20151006",
    "20151013",
    "20151020",
    "20151027",
    "20151103",
    "20151110",
    "20151117",
    "20151124",
    "20151201",
    "20151208",
    "20151215",
    "20151222",
    "20151229",
]


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


def _write_issue_zip(path: Path, stamp: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"USDM_{stamp}_M/USDM_{stamp}.gml", "<gml/>")


def _write_authoritative_shape_archives(root: Path) -> None:
    issues = expected_issue_dates()
    for year in (2014, 2015, 2016):
        path = root / f"{year}_USDM_GML.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for issue in issues:
                if issue.year != year:
                    continue
                if year == 2015 and issue.month >= 10:
                    continue
                stamp = issue.strftime("%Y%m%d")
                archive.writestr(f"USDM_{stamp}_M/USDM_{stamp}.gml", "<gml/>")
    for stamp in SUPPLEMENTAL_2015:
        _write_issue_zip(root / f"usdm_{stamp}_gml.zip", stamp)


def test_authoritative_issue_calendar_excludes_known_2016_non_issue():
    issues = expected_issue_dates()
    assert len(issues) == 155
    assert {
        date(2016, 11, 1): "absent_from_official_gml_archive_and_weekly_object_returns_404"
    } == KNOWN_NON_ISSUE_DATES
    assert date(2016, 11, 1) not in issues


def test_mgvb_offline_freeze_certify_and_replay(tmp_path: Path):
    offline = tmp_path / "offline"
    offline.mkdir()
    _write_authoritative_shape_archives(offline)
    evidence = tmp_path / "evidence"
    manifest_path, manifest_sha = freeze(evidence, offline_input_dir=offline)
    result = certify(manifest_path)
    assert result == {
        "source_family": "USDM",
        "annual_objects": 3,
        "supplemental_weekly_objects": 13,
        "week_count": 155,
        "known_non_issue_dates": ["2016-11-01"],
        "missing": 0,
        "unexpected": 0,
        "status": "certified",
    }
    replay_result = replay(manifest_path, manifest_sha)
    assert replay_result["status"] == "replay_pass"
    assert replay_result["network_required"] is False
