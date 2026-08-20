from __future__ import annotations

import json
from pathlib import Path


PATH = Path("ontology/ebas_non_aaa_operator_universe.v0.1.json")


def load() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_source_domains_are_decoded_from_geodatabase_metadata() -> None:
    data = load()["source_snapshot_2015"]
    assert data["owner_domain"] == {
        "PRASA": "AAA",
        "PRV": "Privado",
        "GOV": "Gobierno",
        "UNK": "Desconocido",
    }
    assert data["lifecycle_domain"]["2"] == "En Uso"
    assert data["lifecycle_domain"]["3"] == "Fuera de Operación Temporera"
    assert data["lifecycle_domain"]["4"] == "Fuera de Operación Permanente"
    assert data["lifecycle_domain"]["5"] == "A Eliminarse"


def test_2015_non_aaa_owned_en_uso_partition_closes() -> None:
    data = load()["source_snapshot_2015"]
    assert data["row_count"] == 1066
    assert sum(data["owner_counts"].values()) == 1066
    assert data["en_uso_counts"] == {"PRASA": 792, "PRV": 87, "GOV": 4, "UNK": 0}
    assert data["non_aaa_owned_en_uso"] == 91
    assert sum(data["non_aaa_owned_en_uso_breakdown"].values()) == 91
    assert len(data["government_en_uso_manifestations"]) == 4


def test_owner_is_not_promoted_to_operator() -> None:
    data = load()
    assert data["identity_effect"] == "none"
    assert data["physical_asset_count_claimed"] is False
    assert data["pr_wide_denominator_claimed"] is False
    assert "do not identify the operator" in data["source_snapshot_2015"]["operator_inference_rule"]


def test_current_non_aaa_system_operators_exist_but_ebas_denominator_stays_open() -> None:
    data = load()
    terminal = data["terminal_state"]
    assert terminal["non_aaa_sanitary_systems_current_exist"] is True
    assert set(terminal["non_aaa_current_system_operators_confirmed"]) == {
        "Local Redevelopment Authority for Roosevelt Roads",
        "PDM Utility Corporation",
        "Coco Beach Utility Company, Inc.",
    }
    assert terminal["current_non_aaa_ebas_denominator"] == "OPEN"
    assert terminal["pr_wide_ebas_denominator"] == "OPEN"


def test_private_franchise_universe_is_not_ebas_denominator() -> None:
    data = load()["private_franchise_universe"]
    assert data["bounded_count"] == 3
    assert set(data["entities"]) == {
        "PDM Utility Corporation",
        "Coco Beach Utility Company",
        "Caguas Real Utility Corp.",
    }
    assert data["not_equivalent_to_ebas_denominator"] is True


def test_federal_and_municipal_fail_closed_controls() -> None:
    data = load()
    federal = next(x for x in data["current_operator_classes"] if x["class"] == "FEDERAL_INSTALLATION_NEGATIVE_CONTROL")
    assert federal["entity"] == "Fort Buchanan"
    assert federal["operator_state"] == "AAA_OPERATED_SANITARY_SERVICE"
    assert data["municipal_operator_test"]["state"] == "NO_INDEPENDENT_MUNICIPAL_POTW_OPERATOR_CERTIFIED_IN_BOUNDED_SEARCH"
