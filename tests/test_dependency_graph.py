"""Tests for `aguayluz.analysis.dependency.build_dependency_graph`."""

from __future__ import annotations

from aguayluz.analysis import GraphEdge, GraphNode, build_dependency_graph
from aguayluz.models import validate_against_schema


def _asset(asset_id: str, **kw) -> dict:  # type: ignore[no-untyped-def]
    base = {
        "asset_id": asset_id,
        "asset_name": kw.pop("name", asset_id),
        "asset_type": kw.pop("asset_type", "water"),
        "asset_subtype": "intake",
        "municipality": kw.pop("municipality", "Toa Alta"),
        "lat": 18.388,
        "lon": -66.232,
        "geometry_type": "point",
        "status": "active",
        "source_ref": "https://api.epa.gov/waters/v1/pointindexing?output=JSON",
        "evidence_tier": "T1",
        "confidence": 70,
        "review_status": "accepted",
        "comid": kw.pop("comid", 21000100),
        "reachcode": kw.pop("reachcode", "21010002000001"),
        "vpuid": kw.pop("vpuid", "21"),
    }
    base.update(kw)
    return base


def _event(event_id: str, area: str) -> dict:
    return {
        "event_id": event_id,
        "event_type": "project_update",
        "affected_area": area,
        "source_ref": "https://www.fema.gov/api/open/v2/Public…",
        "evidence_tier": "T2",
        "confidence": 45,
        "review_status": "needs_review",
        "linked_asset_ids": [],
    }


# ---------- nodes ----------


def test_nodes_for_assets_and_events():
    nodes, _ = build_dependency_graph(
        assets=[_asset("AYL_AST_A")],
        events=[_event("AYL_EVT_20170920_fema_4339_pw1", "Toa Alta, PR — Utilities")],
    )
    by_kind = {n.kind for n in nodes}
    assert by_kind == {"asset", "event"}
    asset_node = next(n for n in nodes if n.kind == "asset")
    assert asset_node.vpuid == "21"
    assert asset_node.municipality == "Toa Alta"


# ---------- edges ----------


def test_same_reach_edges_when_two_assets_share_reachcode():
    _, edges = build_dependency_graph(
        assets=[
            _asset("AYL_AST_A", reachcode="21010002000001"),
            _asset("AYL_AST_B", reachcode="21010002000001"),
            _asset("AYL_AST_C", reachcode="21010002000999"),
        ],
        events=[],
    )
    same_reach = [e for e in edges if e.kind == "same_reach"]
    assert len(same_reach) == 1
    assert (same_reach[0].from_id, same_reach[0].to_id) == ("AYL_AST_A", "AYL_AST_B")
    assert "21010002000001" in same_reach[0].evidence


def test_same_municipality_edges_skip_uniques():
    _, edges = build_dependency_graph(
        assets=[
            _asset("AYL_AST_TOA1", municipality="Toa Alta"),
            _asset("AYL_AST_TOA2", municipality="Toa Alta"),
            _asset("AYL_AST_PONCE", municipality="Ponce"),
        ],
        events=[],
    )
    same_muni = [e for e in edges if e.kind == "same_municipality"]
    assert len(same_muni) == 1
    assert {same_muni[0].from_id, same_muni[0].to_id} == {"AYL_AST_TOA1", "AYL_AST_TOA2"}


def test_affects_municipality_event_to_asset():
    _, edges = build_dependency_graph(
        assets=[_asset("AYL_AST_TOA", municipality="Toa Alta")],
        events=[
            _event("AYL_EVT_20170920_fema_4339_pw1", "Toa Alta, PR — Utilities"),
            _event("AYL_EVT_20170920_fema_4339_pw2", "Ponce, PR — Utilities"),
        ],
    )
    affects = [e for e in edges if e.kind == "affects_municipality"]
    assert len(affects) == 1
    assert affects[0].from_id == "AYL_EVT_20170920_fema_4339_pw1"
    assert affects[0].to_id == "AYL_AST_TOA"


def test_shares_disaster_event_to_event():
    _, edges = build_dependency_graph(
        assets=[],
        events=[
            _event("AYL_EVT_20170920_fema_4339_pw1", "Toa Alta, PR — Utilities"),
            _event("AYL_EVT_20170920_fema_4339_pw2", "Ponce, PR — Utilities"),
            _event("AYL_EVT_20200227_fema_4473_pw9", "Ponce, PR — Utilities"),
        ],
    )
    shares = [e for e in edges if e.kind == "shares_disaster"]
    assert len(shares) == 1
    assert "4339" in shares[0].evidence


def test_no_nav_fn_yields_no_downstream_edges():
    _, edges = build_dependency_graph(
        assets=[
            _asset("AYL_AST_A", comid=21000100),
            _asset("AYL_AST_B", comid=21000101),
        ],
        events=[],
        nav_fn=None,
    )
    assert all(e.kind != "downstream_of" for e in edges)


def test_nav_fn_emits_downstream_edges():
    """When asset A's downstream trace hits asset B's COMID, emit B downstream_of A."""

    def nav_fn(comid: int, _dist: int) -> list[dict]:
        # Downstream of 21000100 hits 21000101.
        if comid == 21000100:
            return [{"comid": 21000101}]
        return []

    _, edges = build_dependency_graph(
        assets=[
            _asset("AYL_AST_UP", comid=21000100, reachcode="REACH_UP"),
            _asset("AYL_AST_DOWN", comid=21000101, reachcode="REACH_DOWN"),
        ],
        events=[],
        nav_fn=nav_fn,
    )
    down = [e for e in edges if e.kind == "downstream_of"]
    assert len(down) == 1
    assert down[0].from_id == "AYL_AST_DOWN"
    assert down[0].to_id == "AYL_AST_UP"


def test_nav_fn_failure_doesnt_crash():
    def boom(_c: int, _d: int) -> list[dict]:
        raise RuntimeError("network down")

    _, edges = build_dependency_graph(
        assets=[_asset("AYL_AST_A"), _asset("AYL_AST_B")],
        events=[],
        nav_fn=boom,
    )
    # Should fall back to heuristics only — no downstream edges, no crash.
    assert all(e.kind != "downstream_of" for e in edges)


# ---------- schema integration ----------


def test_graph_dict_validates_against_schema():
    nodes, edges = build_dependency_graph(
        assets=[
            _asset("AYL_AST_A"),
            _asset("AYL_AST_B"),
        ],
        events=[_event("AYL_EVT_20170920_fema_4339_pw1", "Toa Alta, PR — Utilities")],
    )
    graph_dict = {
        "module_id": "aguayluz-pr",
        "run_id": "20260606T120000Z_test",
        "vector": "AGUAYLUZ_BUILD_DEPENDENCY_GRAPH",
        "generated_at": "2026-06-06T12:00:00Z",
        "nodes": [
            {
                "id": n.id,
                "kind": n.kind,
                "label": n.label,
                "municipality": n.municipality,
                "asset_type": n.asset_type,
                "vpuid": n.vpuid,
            }
            for n in nodes
        ],
        "edges": [e.model_dump() for e in edges],
    }
    validate_against_schema("dependency_graph", graph_dict)


# ---------- dataclass behavior ----------


def test_graph_edge_model_dump_uses_from_to_keys():
    e = GraphEdge(
        from_id="A", to_id="B", kind="same_reach",
        evidence="test", weight=1.0, confidence=80,
    )
    d = e.model_dump()
    assert d["from"] == "A" and d["to"] == "B"
    assert "from_id" not in d


def test_graph_node_basic_fields():
    n = GraphNode(id="X", kind="asset", label="Asset X")
    assert n.id == "X"
    assert n.municipality is None


# ---------- nav_distance_km propagation ----------


def test_nav_distance_km_threaded_to_nav_fn():
    """The build_dependency_graph caller can pick the distance; the analyzer
    forwards it verbatim to nav_fn for each asset."""
    captured: list[tuple[int, int]] = []

    def spying_nav(comid: int, distance_km: int) -> list[dict]:
        captured.append((comid, distance_km))
        return []

    build_dependency_graph(
        assets=[_asset("AYL_AST_A", comid=21000100), _asset("AYL_AST_B", comid=21000101)],
        events=[],
        nav_fn=spying_nav,
        nav_distance_km=7,
    )
    assert all(d == 7 for _, d in captured)
    assert {c for c, _ in captured} == {21000100, 21000101}
