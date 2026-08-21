from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from aguayluz.models import validate_against_schema
from research.drought_resilience import (
    TrajectoryRule,
    assess_rapid_onset,
    build_drought_state,
    drought_state_to_alert_candidate,
    validate_water_supply_system,
)


def _validate_local(schema_name: str, obj: dict) -> None:
    import json
    from pathlib import Path

    path = Path("schemas/drought-resilience/v0.1") / schema_name
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(obj)


def _hydro_state(state: str = "watch") -> dict:
    return build_drought_state(
        drought_class="hydrological",
        state=state,
        observed_date="2026-08-12",
        geography_id="BASIN_TEST_001",
        source_ref="https://example.test/authoritative-hydro",
        evidence_tier="T1",
        confidence=90,
        review_status="accepted",
        methodology_ref="https://example.test/method-v1",
        indicators=[
            {
                "metric": "reservoir_storage_pct",
                "value": 42.0,
                "unit": "%",
                "source_ref": "https://example.test/authoritative-hydro",
                "reading_id": "AYL_RDG_20260812_TEST_reservoir_storage_pct",
                "qualifier": None,
            }
        ],
    )


def test_drought_state_schema_accepts_one_class_only():
    state = _hydro_state()
    _validate_local("drought_state.schema.json", state)
    assert state["drought_class"] == "hydrological"
    assert "meteorological_state" not in state


def test_drought_state_is_deterministic():
    assert _hydro_state()["drought_state_id"] == _hydro_state()["drought_state_id"]


def test_drought_state_rejects_cross_class_container():
    bad = _hydro_state()
    bad["meteorological_state"] = "drought"
    with pytest.raises(ValidationError):
        _validate_local("drought_state.schema.json", bad)


def test_rapid_onset_decrease_triggers_only_against_explicit_rule():
    readings = [
        {"metric": "reservoir_storage_pct", "observed_date": "2026-08-01", "value": 60.0},
        {"metric": "reservoir_storage_pct", "observed_date": "2026-08-06", "value": 55.0},
        {"metric": "reservoir_storage_pct", "observed_date": "2026-08-11", "value": 48.0},
    ]
    rule = TrajectoryRule(
        metric="reservoir_storage_pct",
        direction="decrease",
        minimum_rate_per_day=1.0,
        minimum_span_days=7,
        minimum_points=3,
        source_ref="https://example.test/rule",
        rule_id="RULE_TEST_001",
    )
    result = assess_rapid_onset(readings, rule)
    assert result["assessment"] == "rapid_decline"
    assert result["signed_rate_per_day"] == pytest.approx(-1.2)
    assert result["concerning_rate_per_day"] == pytest.approx(1.2)
    _validate_local("rapid_onset_assessment.schema.json", result)


def test_rapid_onset_fails_closed_without_enough_span():
    rule = TrajectoryRule(
        metric="reservoir_storage_pct",
        direction="decrease",
        minimum_rate_per_day=0.1,
        minimum_span_days=7,
        source_ref="https://example.test/rule",
    )
    result = assess_rapid_onset(
        [
            {"metric": "reservoir_storage_pct", "observed_date": "2026-08-10", "value": 50},
            {"metric": "reservoir_storage_pct", "observed_date": "2026-08-12", "value": 40},
        ],
        rule,
    )
    assert result["assessment"] == "not_assessable"
    assert result["reason"] == "insufficient_span"
    _validate_local("rapid_onset_assessment.schema.json", result)


def test_rapid_onset_rule_requires_provenance():
    rule = TrajectoryRule(
        metric="reservoir_storage_pct",
        direction="decrease",
        minimum_rate_per_day=0.1,
        source_ref="",
    )
    with pytest.raises(ValueError, match="source_ref"):
        assess_rapid_onset([], rule)


def test_supply_graph_accepts_bound_declared_topology():
    system = {
        "system_id": "AYL_WSS_TEST_001",
        "name": "Test water system",
        "as_of": "2026-08-12",
        "source_ref": "https://example.test/system",
        "review_status": "accepted",
        "nodes": [
            {"node_id": "SRC", "node_type": "source", "name": "Reservoir", "asset_id": None, "source_kind": "reservoir", "municipality": None},
            {"node_id": "INT", "node_type": "intake", "name": "Intake", "asset_id": None, "source_kind": "not_applicable", "municipality": None},
            {"node_id": "TRT", "node_type": "treatment", "name": "Plant", "asset_id": None, "source_kind": "not_applicable", "municipality": None},
            {"node_id": "DEM", "node_type": "demand", "name": "Demand area", "asset_id": None, "source_kind": "not_applicable", "municipality": None},
        ],
        "edges": [
            {"edge_id": "E1", "from_node_id": "SRC", "to_node_id": "INT", "binding_ref": "https://example.test/e1", "binding_type": "authoritative_record", "confidence": 100},
            {"edge_id": "E2", "from_node_id": "INT", "to_node_id": "TRT", "binding_ref": "https://example.test/e2", "binding_type": "operator_document", "confidence": 95},
            {"edge_id": "E3", "from_node_id": "TRT", "to_node_id": "DEM", "binding_ref": "https://example.test/e3", "binding_type": "authoritative_record", "confidence": 100},
        ],
    }
    _validate_local("water_supply_system.schema.json", system)
    assert validate_water_supply_system(system) == []


def test_supply_graph_rejects_unproven_and_dangling_edges():
    system = {
        "nodes": [{"node_id": "A", "node_type": "source", "name": "A"}],
        "edges": [
            {"edge_id": "E1", "from_node_id": "A", "to_node_id": "B", "binding_ref": ""}
        ],
    }
    errors = validate_water_supply_system(system)
    assert "dangling_edge:E1" in errors
    assert "unproven_edge:E1" in errors


def test_alert_crosswalk_is_draft_and_existing_schema_valid():
    candidate = drought_state_to_alert_candidate(_hydro_state("rapid_decline"))
    assert candidate["status"] == "draft"
    assert candidate["module_id"] == "HYDRO_OPS"
    assert candidate["event_type"] == "hazard"
    assert candidate["review_status"] == "needs_review"
    assert "no automatic cross-class inference" in candidate["validation_notes"]
    validate_against_schema("alert_event", candidate)


def test_alert_crosswalk_does_not_activate_or_link_assets_by_proximity():
    candidate = drought_state_to_alert_candidate(_hydro_state("drought"))
    assert candidate["status"] != "active"
    assert candidate["linked_asset_ids"] == []
    assert candidate["asset_id"] is None
