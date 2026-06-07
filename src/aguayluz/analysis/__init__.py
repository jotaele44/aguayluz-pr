"""Cross-entity analysis (graphs, summaries, dependency mapping)."""

from .dependency import GraphEdge, GraphNode, build_dependency_graph
from .reconciliation import Finding, reconcile

__all__ = ["GraphEdge", "GraphNode", "build_dependency_graph", "Finding", "reconcile"]
