from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


def _validator_module() -> dict:
    return runpy.run_path(str(_REPO / "ontology" / "tools" / "validate_infrastructure_sidecars.py"))


def _fixture() -> dict:
    return json.loads((_REPO / "tests" / "fixtures" / "ebas_vertical_slice.json").read_text(encoding="utf-8"))


def test_ebas_fixture_graph_closes_without_orphans() -> None:
    module = _validator_module()
    module["validate_object_graph"](_fixture()["objects"], _fixture()["relations"])


def test_self_loop_and_orphan_relation_fail_closed() -> None:
    module = _validator_module()
    fixture = _fixture()

    self_loop = copy.deepcopy(fixture["relations"])
    self_loop[0]["to_object_id"] = self_loop[0]["from_object_id"]
    with pytest.raises(ValueError, match="self-loop"):
        module["validate_object_graph"](fixture["objects"], self_loop)

    orphan = copy.deepcopy(fixture["relations"])
    orphan[0]["to_object_id"] = "AYL_MISSING_OBJECT"
    with pytest.raises(ValueError, match="orphan relation endpoint"):
        module["validate_object_graph"](fixture["objects"], orphan)


def test_component_parent_and_site_reference_are_typed() -> None:
    module = _validator_module()
    fixture = _fixture()
    objects = copy.deepcopy(fixture["objects"])
    component = objects[2]
    component["parent_object_id"] = objects[0]["object_id"]
    with pytest.raises(ValueError, match="component parent must be an asset"):
        module["validate_object_graph"](objects, fixture["relations"])


def test_invalid_temporal_relation_interval_fails_closed() -> None:
    module = _validator_module()
    fixture = _fixture()
    relations = copy.deepcopy(fixture["relations"])
    relations[0]["valid_from"] = "2026-08-16T12:00:00+00:00"
    relations[0]["valid_to"] = "2026-08-15T12:00:00+00:00"
    with pytest.raises(ValueError, match="invalid temporal interval"):
        module["validate_object_graph"](fixture["objects"], relations)
