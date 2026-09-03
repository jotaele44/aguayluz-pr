from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BALLOT_PATH = (
    ROOT
    / "docs"
    / "architecture"
    / "water_balance_implementation_ballot_v0.3.json"
)
SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "water-balance"
    / "v0.3"
    / "implementation-ballot.schema.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_implementation_ballot_validates() -> None:
    schema = _load(SCHEMA_PATH)
    ballot = _load(BALLOT_PATH)

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(ballot)


def test_reviewed_pr_heads_and_decisions_are_pinned() -> None:
    reviewed = _load(BALLOT_PATH)["reviewed_prs"]

    assert reviewed == {
        "asset_graph": {
            "pr": 101,
            "head_sha": "c50855876c57c0d10cd3bcea81a6998814863a09",
            "decision": "adapt",
        },
        "usgs_hardened_parsers": {
            "pr": 109,
            "head_sha": "651ad41e8bbcbd7f1877bb14436bb19a1bcfab2a",
            "decision": "adapt_selected_semantics_only",
        },
        "usgs_provider_framework": {
            "pr": 116,
            "head_sha": "628a7da4dddb0622f07d97850bf79a0567bdef3e",
            "decision": "adapt_framework_only",
        },
        "laguna_control_plane": {
            "pr": 118,
            "head_sha": "b82c724072d46631bc563c9562948d11119b4cc6",
            "decision": "adapt_secondary_pilot_hold_operational_balance",
        },
    }


def test_relationships_fail_closed_until_hydraulic_adjudication() -> None:
    edges = _load(BALLOT_PATH)["edge_classification"]
    expected = {
        "UPSTREAM_OF",
        "DOWNSTREAM_OF",
        "SUPPLIES",
        "DEPENDS_ON",
        "POWERED_BY",
        "BACKUP_FOR",
        "LOCATED_IN",
        "SERVES",
        "MONITORED_BY",
        "UNKNOWN",
    }

    assert {edge["relationship_type"] for edge in edges} == expected
    assert len(edges) == len(expected)
    assert all(edge["balance_eligible_by_default"] is False for edge in edges)

    supplies = next(edge for edge in edges if edge["relationship_type"] == "SUPPLIES")
    assert "not_mapped_from_energizes" in supplies["promotion_requirements"]


def test_usgs_lane_has_one_producer_and_stable_source_namespaces() -> None:
    decision = _load(BALLOT_PATH)["usgs_acquisition_decision"]

    assert decision["producer_rule"] == "exactly_one_producer_per_collection"
    assert decision["framework_source"] == "PR116"
    assert decision["field_measurement_semantics_source"] == "PR109"
    assert decision["annual_peak_semantics_source"] == "PR109"
    assert decision["source_asset_prefixes"] == {
        "surface_water": "USGS_",
        "groundwater_daily_values": "USGSGW_",
        "groundwater_field_measurements": "USGSFM_",
    }
    assert decision["canonical_source_equivalence_key"] == (
        "usgs:monitoring-location:<bare_site_number>"
    )
    assert "prefix_wide_USGSFM_asset_replacement" in decision["rejected"]


def test_component_matrix_has_no_runtime_activation() -> None:
    components = _load(BALLOT_PATH)["components"]
    by_name = {component["component"]: component for component in components}

    assert len(by_name) == len(components)
    assert all(component["runtime_activation"] is False for component in components)
    assert by_name["balance_api"]["decision"] == "hold"
    assert by_name["balance_gui"]["decision"] == "hold"
    assert by_name["balance_alert_promotion"]["decision"] == "hold"
    assert by_name["balance_incident_promotion"]["decision"] == "hold"
    assert by_name["balance_federation_export"]["decision"] == "hold"


def test_selected_pilot_is_blocked_and_fail_closed() -> None:
    pilot = _load(BALLOT_PATH)["selected_pilot"]

    assert pilot["pilot_id"] == "carraizo_lago_loiza_hydrologic_reservoir_shadow"
    assert pilot["state"] == "selected_blocked"
    assert set(pilot["permitted_pre_entry_result"]) == {
        "underdetermined",
        "not_evaluated",
    }
    assert pilot["public_output"] is False
    assert pilot["incident_promotion"] is False
    assert pilot["alert_promotion"] is False


def test_every_prohibited_action_remains_false() -> None:
    ballot = _load(BALLOT_PATH)

    assert ballot["design_only"] is True
    assert ballot["parent_pr"] == 119
    assert ballot["parent_head_sha"] == (
        "5c3fcb3a5803773ad388b91afc5bc288d4fd4c80"
    )
    assert ballot["prohibitions"]
    assert all(value is False for value in ballot["prohibitions"].values())
