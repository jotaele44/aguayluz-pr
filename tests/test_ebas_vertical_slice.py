from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebas_vertical_slice.json"
OBJECT_SCHEMA = ROOT / "schemas" / "infrastructure_object.schema.json"
RELATION_SCHEMA = ROOT / "schemas" / "infrastructure_relation.schema.json"
REGISTRY = ROOT / "ontology" / "infrastructure_terms.v0.1.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_ebas_fixture_is_explicitly_noncanonical():
    fixture = load(FIXTURE)
    assert fixture["fixture_state"] == "NONCANONICAL_FIXTURE_ONLY"
    assert all(obj["identity_state"] == "noncanonical_fixture" for obj in fixture["objects"])
    assert all(obj["review_status"] == "fixture_only" for obj in fixture["objects"])
    assert all(rel["review_status"] == "fixture_only" for rel in fixture["relations"])


def test_ebas_objects_and_relations_validate():
    fixture = load(FIXTURE)
    object_validator = Draft202012Validator(load(OBJECT_SCHEMA))
    relation_validator = Draft202012Validator(load(RELATION_SCHEMA))
    for obj in fixture["objects"]:
        object_validator.validate(obj)
    for relation in fixture["relations"]:
        relation_validator.validate(relation)


def test_ebas_asset_and_wet_well_component_remain_distinct():
    fixture = load(FIXTURE)
    by_id = {obj["object_id"]: obj for obj in fixture["objects"]}
    ebas = by_id["AYL_FIX_ASSET_EBAS_001"]
    wet_well = by_id["AYL_FIX_COMPONENT_WET_WELL_001"]
    assert ebas["canonical_term_id"] == "AYL_TERM_SANITARY_SEWER_PUMP_STATION"
    assert ebas["feature_kind"] == "asset"
    assert wet_well["canonical_term_id"] == "AYL_TERM_WET_WELL"
    assert wet_well["feature_kind"] == "component"
    assert wet_well["parent_object_id"] == ebas["object_id"]
    assert wet_well["object_id"] != ebas["object_id"]


def test_component_relation_has_no_identity_effect():
    fixture = load(FIXTURE)
    matches = [rel for rel in fixture["relations"] if rel["relation_type"] == "component_of"]
    assert len(matches) == 1
    relation = matches[0]
    assert relation["from_object_id"] == "AYL_FIX_COMPONENT_WET_WELL_001"
    assert relation["to_object_id"] == "AYL_FIX_ASSET_EBAS_001"
    assert relation["identity_effect"] == "none"


def test_ebas_is_alias_not_canonical_peer_label():
    registry = load(REGISTRY)
    labels = {term["canonical_label"] for term in registry["terms"]}
    assert "EBAS" not in labels
    aliases = [alias for alias in registry["aliases"] if alias["alias"] == "EBAS"]
    assert len(aliases) == 1
    assert aliases[0]["canonical_term_id"] == "AYL_TERM_SANITARY_SEWER_PUMP_STATION"
    assert aliases[0]["identity_effect"] == "none"


def test_fixture_graph_references_existing_objects():
    fixture = load(FIXTURE)
    object_ids = {obj["object_id"] for obj in fixture["objects"]}
    assert len(object_ids) == len(fixture["objects"])
    for relation in fixture["relations"]:
        assert relation["from_object_id"] in object_ids
        assert relation["to_object_id"] in object_ids
