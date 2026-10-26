"""Negative and positive contract tests for candidate source catalog."""
import copy
import json
from pathlib import Path

from scripts.validate_gis_source_candidates import validate_catalog


def fixtures():
    return (json.loads(Path("config/gis_source_candidates.v1.json").read_text()),
            json.loads(Path("config/master_gis_layer_registry.v1.json").read_text()))


def test_candidate_catalog_structure():
    assert validate_catalog(*fixtures()) == []


def test_unknown_group_rejected():
    catalog, registry = fixtures()
    catalog["records"][0]["group_id"] = "not_a_group"
    assert validate_catalog(catalog, registry)


def test_duplicate_candidate_rejected():
    catalog, registry = fixtures()
    catalog["records"].append(copy.deepcopy(catalog["records"][0]))
    assert validate_catalog(catalog, registry)


def test_unverified_completeness_rejected():
    catalog, registry = fixtures()
    catalog["completeness_claimed"] = True
    assert validate_catalog(catalog, registry)


def test_source_count_mismatch_rejected():
    catalog, registry = fixtures()
    catalog["records"][0].update(record_count=3, retained_count=1, excluded_count=1, unresolved_count=0)
    assert any("closure" in x for x in validate_catalog(catalog, registry))


def test_partial_count_rejected():
    catalog, registry = fixtures()
    catalog["records"][0]["record_count"] = 4
    assert any("partial" in x for x in validate_catalog(catalog, registry))
