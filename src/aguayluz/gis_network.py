"""Dependency tracing and outage scenarios for the GIS viewer (``/gis/trace``, ``/gis/scenario``).

Builds on :mod:`aguayluz.spatial_analysis` (``DirectedEdge`` / ``trace_*``) and the
recorded dependency links in ``data/alert_dependency_edges.jsonl``. What this
module adds is *path evidence*: every traced feature reports the link that first
reached it, the weakest confidence on its path and whether any link on that path
still needs evidence. Most recorded power -> water links are proximity proxies
("proximity, not a verified circuit"), so results must be able to say so.

* :func:`trace` is a breadth-first walk in the same deterministic order as
  ``spatial_analysis._trace`` (sorted neighbours, hop limit), so its feature set
  equals ``trace_downstream`` / ``trace_upstream``.
* :func:`scenario_out_of_service` returns a ``gis-scenario-result/1.0`` document
  (``schemas/gis_scenario_result_v1.schema.json``): always ``HYPOTHESIS``, never
  persisted.

Pure functions: no I/O, no clock.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from aguayluz.spatial_analysis import DirectedEdge

CONTRACT_SCENARIO = "gis-scenario-result/1.0"
PRODUCER_REPO = "aguayluz-pr"
DEFAULT_MAX_HOPS = 25
PROXY_NOTE = (
    "Relies on proximity-proxy dependencies (evidence_required): these links were "
    "inferred from distance, not verified circuits or service assignments."
)


@dataclass(frozen=True)
class NetworkEdge:
    """One recorded dependency link, directed from the supplier to the dependent."""

    edge_id: str
    from_id: str
    to_id: str
    from_type: str | None
    to_type: str | None
    relation: str
    confidence: float | None
    evidence_required: bool
    notes: str | None

    def directed(self) -> DirectedEdge:
        return DirectedEdge(self.from_id, self.to_id, self.relation)


@dataclass(frozen=True)
class TraceHit:
    feature_id: str
    node_type: str | None
    hops: int
    edge_id: str
    relation: str
    confidence: float | None
    evidence_required: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "node_type": self.node_type,
            "hops": self.hops,
            "edge_id": self.edge_id,
            "relation": self.relation,
            "confidence": self.confidence,
            "evidence_required": self.evidence_required,
        }


def _confidence(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 <= value <= 100 else None


def edges_from_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[list[NetworkEdge], int]:
    """Parse dependency rows; rows without both endpoints are counted, not guessed."""
    edges: list[NetworkEdge] = []
    excluded = 0
    for row in rows:
        from_id = row.get("from_node_id") or row.get("from_asset_id")
        to_id = row.get("to_node_id") or row.get("to_asset_id")
        if not isinstance(from_id, str) or not isinstance(to_id, str) or not from_id or not to_id:
            excluded += 1
            continue
        edges.append(
            NetworkEdge(
                edge_id=str(row.get("edge_id") or f"{from_id}->{to_id}"),
                from_id=from_id,
                to_id=to_id,
                from_type=row.get("from_node_type"),
                to_type=row.get("to_node_type"),
                relation=str(row.get("dependency_type") or row.get("relation") or "DEPENDS_ON"),
                confidence=_confidence(row.get("confidence")),
                evidence_required=bool(row.get("evidence_required", False)),
                notes=row.get("notes") if isinstance(row.get("notes"), str) else None,
            )
        )
    return edges, excluded


def _adjacency(
    edges: Iterable[NetworkEdge], direction: str
) -> dict[str, list[tuple[str, NetworkEdge]]]:
    graph: dict[str, dict[str, NetworkEdge]] = {}
    for edge in edges:
        if edge.from_id == edge.to_id:
            continue
        src, dst = (edge.from_id, edge.to_id) if direction == "downstream" else (edge.to_id, edge.from_id)
        current = graph.setdefault(src, {}).get(dst)
        # Several links between the same pair: keep the best-evidenced one.
        if current is None or _edge_rank(edge) > _edge_rank(current):
            graph[src][dst] = edge
    return {node: sorted(nbrs.items()) for node, nbrs in graph.items()}


def _edge_rank(edge: NetworkEdge) -> tuple[int, float, str]:
    return (0 if edge.evidence_required else 1, edge.confidence or 0.0, edge.edge_id)


def trace(
    start_id: str,
    edges: Sequence[NetworkEdge],
    *,
    direction: str = "downstream",
    max_hops: int = DEFAULT_MAX_HOPS,
) -> list[TraceHit]:
    """Features reachable from ``start_id``, nearest first, with path evidence."""
    if direction not in ("downstream", "upstream"):
        raise ValueError("direction must be 'downstream' or 'upstream'")
    if max_hops < 0:
        raise ValueError("max_hops must be non-negative")
    graph = _adjacency(edges, direction)
    seen = {start_id}
    queue: deque[tuple[str, int, float | None, bool]] = deque([(start_id, 0, None, False)])
    hits: list[TraceHit] = []
    while queue:
        node, depth, path_conf, path_proxy = queue.popleft()
        if depth >= max_hops:
            continue
        for nxt, edge in graph.get(node, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            confs = [c for c in (path_conf, edge.confidence) if c is not None]
            conf = min(confs) if confs else None
            proxy = path_proxy or edge.evidence_required
            node_type = edge.to_type if direction == "downstream" else edge.from_type
            hits.append(TraceHit(nxt, node_type, depth + 1, edge.edge_id, edge.relation, conf, proxy))
            queue.append((nxt, depth + 1, conf, proxy))
    return hits


def edge_set_sha256(edges: Sequence[NetworkEdge]) -> str:
    payload = sorted(
        (e.edge_id, e.from_id, e.to_id, e.relation, e.confidence, e.evidence_required) for e in edges
    )
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


AreaLookup = Callable[[str], Sequence[tuple[str, str, str | None]]]
LayerLookup = Callable[[str], str | None]


def scenario_out_of_service(
    selected: Sequence[tuple[str, str]],
    edges: Sequence[NetworkEdge],
    *,
    layer_of: LayerLookup,
    areas_of: AreaLookup,
    max_hops: int = DEFAULT_MAX_HOPS,
) -> dict[str, Any]:
    """What would lose service if ``selected`` features went out of service.

    ``selected`` is ``[(layer_id, feature_id), ...]``. ``layer_of`` maps a node id
    to its catalog layer (or ``None``); ``areas_of`` maps a node id to
    ``[(area_type, area_id, name), ...]`` (municipio, service area, ...).
    """
    if not selected:
        raise ValueError("select at least one feature")
    chosen = sorted({feature_id for _layer, feature_id in selected})
    best: dict[str, TraceHit] = {}
    for feature_id in chosen:
        for hit in trace(feature_id, edges, direction="downstream", max_hops=max_hops):
            if hit.feature_id in chosen:
                continue
            prior = best.get(hit.feature_id)
            if prior is None or hit.hops < prior.hops:
                best[hit.feature_id] = hit
    impacted = sorted(best.values(), key=lambda h: (h.hops, h.feature_id))
    areas: dict[tuple[str, str], str | None] = {}
    for hit in impacted:
        if hit.node_type == "service_area":
            areas.setdefault(("service_area", hit.feature_id), None)
        for area_type, area_id, name in areas_of(hit.feature_id):
            areas.setdefault((area_type, area_id), name)
    unverified = any(hit.evidence_required for hit in impacted)
    inputs = {
        "selected": [{"layer_id": layer_id, "feature_id": feature_id} for layer_id, feature_id in sorted(set(selected))],
        "parameters": {"out_of_service": True, "direction": "downstream", "max_hops": max_hops},
    }
    scenario_id = hashlib.sha256(
        json.dumps(
            {"kind": "out_of_service", "inputs": inputs, "edges_sha256": edge_set_sha256(edges)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    notes = [
        f"{len(chosen)} feature(s) marked out of service; downstream dependents only, up to {max_hops} hops.",
        "A feature counts as impacted when a recorded link reaches it; supply alternatives and redundancy are not modelled.",
    ]
    if unverified:
        notes.insert(0, PROXY_NOTE)
    return {
        "contract_version": CONTRACT_SCENARIO,
        "producer_repo": PRODUCER_REPO,
        "scenario_id": scenario_id,
        "scenario_kind": "out_of_service",
        "inputs": inputs,
        "impacted": [
            {
                "layer_id": layer_of(hit.feature_id),
                "feature_id": hit.feature_id,
                "hops": hit.hops,
                "relation": hit.relation,
                "edge_id": hit.edge_id,
                "confidence": hit.confidence,
                "evidence_required": hit.evidence_required,
            }
            for hit in impacted
        ],
        "affected_areas": [
            {"area_type": area_type, "area_id": area_id, "name": name}
            for (area_type, area_id), name in sorted(areas.items())
        ],
        "unverified_links_used": unverified,
        "evidence_state": "HYPOTHESIS",
        "persisted": False,
        "notes": notes,
    }
