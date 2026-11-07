"""Dependency tracing with path evidence, and out-of-service scenarios."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aguayluz import gis_network as net
from aguayluz.spatial_analysis import trace_downstream, trace_upstream

ROOT = Path(__file__).resolve().parents[1]

ROWS = [
    {"edge_id": "E1", "from_node_id": "P1", "to_node_id": "W1", "dependency_type": "energizes",
     "confidence": 90, "evidence_required": False, "from_node_type": "power_node", "to_node_type": "hydro_asset"},
    {"edge_id": "E2", "from_node_id": "W1", "to_node_id": "W2", "dependency_type": "supplies",
     "confidence": 40, "evidence_required": True, "from_node_type": "hydro_asset", "to_node_type": "hydro_asset"},
    {"edge_id": "E3", "from_node_id": "W2", "to_node_id": "SA1", "dependency_type": "supplies",
     "confidence": 70, "evidence_required": False, "from_node_type": "hydro_asset", "to_node_type": "service_area"},
    {"edge_id": "E4", "from_node_id": None, "to_node_id": "W2", "dependency_type": "threatens"},
]


def test_rows_without_both_endpoints_are_counted_not_guessed():
    edges, excluded = net.edges_from_rows(ROWS)
    assert [e.edge_id for e in edges] == ["E1", "E2", "E3"]
    assert excluded == 1


def test_trace_matches_spatial_analysis_feature_sets():
    edges, _ = net.edges_from_rows(ROWS)
    directed = [e.directed() for e in edges]
    assert [h.feature_id for h in net.trace("P1", edges)] == trace_downstream("P1", directed)
    assert [h.feature_id for h in net.trace("SA1", edges, direction="upstream")] == trace_upstream("SA1", directed)


def test_trace_carries_weakest_confidence_and_proxy_flag_down_the_path():
    edges, _ = net.edges_from_rows(ROWS)
    hits = {h.feature_id: h for h in net.trace("P1", edges)}
    assert (hits["W1"].confidence, hits["W1"].evidence_required) == (90.0, False)
    assert (hits["W2"].confidence, hits["W2"].evidence_required) == (40.0, True)
    assert (hits["SA1"].confidence, hits["SA1"].evidence_required, hits["SA1"].hops) == (40.0, True, 3)
    assert [h.feature_id for h in net.trace("P1", edges, max_hops=1)] == ["W1"]


def test_trace_rejects_bad_direction_and_hops():
    edges, _ = net.edges_from_rows(ROWS)
    with pytest.raises(ValueError):
        net.trace("P1", edges, direction="sideways")
    with pytest.raises(ValueError):
        net.trace("P1", edges, max_hops=-1)


def test_scenario_is_a_labelled_hypothesis_that_validates():
    jsonschema = pytest.importorskip("jsonschema")
    edges, _ = net.edges_from_rows(ROWS)
    result = net.scenario_out_of_service(
        [("power_assets", "P1")],
        edges,
        layer_of=lambda node: "water_assets" if node.startswith("W") else None,
        areas_of=lambda node: [("municipio", "72127", "San Juan")] if node == "W1" else [],
    )
    schema = json.loads((ROOT / "schemas" / "gis_scenario_result_v1.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(result, schema)
    assert result["evidence_state"] == "HYPOTHESIS" and result["persisted"] is False
    assert result["unverified_links_used"] is True
    assert result["notes"][0] == net.PROXY_NOTE
    assert [i["feature_id"] for i in result["impacted"]] == ["W1", "W2", "SA1"]
    assert {(a["area_type"], a["area_id"]) for a in result["affected_areas"]} == {
        ("municipio", "72127"),
        ("service_area", "SA1"),
    }


def test_scenario_id_is_deterministic_and_input_sensitive():
    edges, _ = net.edges_from_rows(ROWS)
    kwargs = {"layer_of": lambda _n: None, "areas_of": lambda _n: []}
    a = net.scenario_out_of_service([("power_assets", "P1")], edges, **kwargs)
    b = net.scenario_out_of_service([("power_assets", "P1")], edges, **kwargs)
    c = net.scenario_out_of_service([("water_assets", "W1")], edges, **kwargs)
    assert a["scenario_id"] == b["scenario_id"] != c["scenario_id"]


def test_verified_only_paths_are_not_labelled_as_proxies():
    edges, _ = net.edges_from_rows(ROWS[:1])
    result = net.scenario_out_of_service(
        [("power_assets", "P1")], edges, layer_of=lambda _n: None, areas_of=lambda _n: []
    )
    assert result["unverified_links_used"] is False
    assert net.PROXY_NOTE not in result["notes"]


def test_recorded_power_to_water_links_are_proxies():
    rows = [json.loads(line) for line in (ROOT / "data" / "alert_dependency_edges.jsonl").read_text().splitlines() if line]
    edges, _ = net.edges_from_rows(rows)
    energizes = [e for e in edges if e.relation == "energizes"]
    assert energizes and all(e.evidence_required for e in energizes)
