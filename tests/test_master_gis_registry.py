"""Contract checks for the planned GIS layer registry."""
import copy
import json
from pathlib import Path

from scripts.validate_master_gis_registry import validate_registry


def _registry():
    return json.loads(Path("config/master_gis_layer_registry.v1.json").read_text())


def test_registry_structure():
    assert validate_registry(_registry()) == []


def test_missing_vieques_fails():
    data = _registry()
    data["scope"]["land"].remove("Vieques")
    assert any("land coverage" in e for e in validate_registry(data))


def test_duplicate_group_fails():
    data = _registry()
    data["groups"].append(copy.deepcopy(data["groups"][0]))
    assert any("unique" in e for e in validate_registry(data))


def test_false_certification_fails():
    data = _registry()
    data["certification_state"] = "PASS"
    assert validate_registry(data)


def test_missing_evidence_firewall_fails():
    data = _registry()
    data["evidence_planes"].remove("HYPOTHETICAL")
    assert validate_registry(data)
