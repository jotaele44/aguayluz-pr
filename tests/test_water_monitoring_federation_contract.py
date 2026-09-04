from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_water_monitoring_capability_inherits_haf_fail_closed_policy() -> None:
    capability = load(".federation/water-monitoring-capability.json")
    haf = load(capability["haf_contract"])
    assert capability["program_id"] == haf["program_id"] == "aguayluz-pr"
    assert capability["certification_required"] is True
    assert haf["certification_required"] is True
    assert capability["fail_closed"] is True
    assert haf["identity_policy"] == "EVIDENCE_PRIORITY_FAIL_CLOSED"
    assert haf["unresolved_policy"] == "FAIL_CLOSED"


def test_complete_scope_cannot_be_certified_with_material_open_residue() -> None:
    capability = load(".federation/water-monitoring-capability.json")
    assert capability["certification_state"] == "PROVISIONAL"
    assert capability["noncertified_layers"]
    assert "extraction" in capability["noncertified_layers"]
    assert "watersheds" in capability["noncertified_layers"]


def test_source_and_layer_registries_are_present_and_scope_aligned() -> None:
    capability = load(".federation/water-monitoring-capability.json")
    source_registry = load(capability["source_registry"])
    layer_registry = load(capability["layer_registry"])
    assert source_registry["scope"] == "Puerto Rico water monitoring"
    assert layer_registry["scope"] == "Puerto Rico water monitoring console"
    source_ids = {source["source_id"] for source in source_registry["sources"]}
    assert len(source_ids) == len(source_registry["sources"])
    assert "sige_pr_watersheds_0" in source_ids
    assert "drna_water_permits_franchises" in source_ids


def test_prohibited_identity_evidence_is_explicit() -> None:
    capability = load(".federation/water-monitoring-capability.json")
    assert set(capability["prohibited_identity_evidence"]) == {
        "NAME_ONLY",
        "NORMALIZED_NAME_ONLY",
        "COUNT_EQUALITY",
        "NEAREST_ONLY",
        "PROXIMITY_ONLY",
        "SAME_CATEGORY",
        "SOURCE_ABSENCE",
    }
