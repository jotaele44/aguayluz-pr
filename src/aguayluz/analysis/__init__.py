"""Cross-entity analysis (graphs, summaries, dependency mapping)."""

from .dependency import GraphEdge, GraphNode, build_dependency_graph
from .municipalities import aggregate_by_municipality
from .reconciliation import Finding, reconcile
from .watersheds import delineate_assets

__all__ = [
    "GraphEdge",
    "GraphNode",
    "build_dependency_graph",
    "Finding",
    "reconcile",
    "delineate_assets",
    "aggregate_by_municipality",
]
