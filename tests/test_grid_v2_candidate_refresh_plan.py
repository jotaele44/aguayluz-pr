"""Refresh-plan gates for the PR Grid V2 USGS source-coordinate candidate exporter."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFRESH = ROOT / "scripts/refresh.py"


def _module():
    spec = importlib.util.spec_from_file_location("aguayluz_refresh", REFRESH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_export_runs_after_usgs_metadata_on_non_fast_plans():
    m = _module()
    candidate = m.STEP_GRID_V2_USGS_SOURCE_COORDINATES
    metadata = m.STEP_USGS_METADATA

    assert candidate not in m.PLANS["fast"]
    for cadence in ("daily", "weekly", "all"):
        plan = m.PLANS[cadence]
        assert plan.count(candidate) == 1
        assert plan.index(candidate) == plan.index(metadata) + 1


def test_candidate_export_is_optional_but_not_silent_geometry_authority():
    m = _module()
    label, argv, optional = m.STEP_GRID_V2_USGS_SOURCE_COORDINATES
    assert "source-coordinate candidates" in label
    assert argv == ["scripts/export_pr_grid_v2_source_coordinate_candidates.py"]
    assert optional is True
