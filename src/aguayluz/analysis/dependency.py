"""Build a dependency graph over `utility_asset` + `service_event` records.

Edge kinds (per `schemas/dependency_graph.schema.json`):
  - same_reach         : two assets snapped to the same NHDPlus reachcode
  - downstream_of      : asset A appears in WATERS upstream-search of asset B
  - upstream_of        : asset A appears in WATERS downstream-search of asset B
  - same_municipality  : two assets share a PR municipality
  - affects_municipality : service event mentions a municipality that contains assets
  - shares_disaster    : two FEMA events share a disaster number

For demo/offline runs, only the heuristics (same_reach, same_municipality,
affects_municipality, shares_disaster) are computed — no WATERS calls. Pass a
`nav_fn(comid, direction)` callable to enable the upstream/downstream lookups
without hard-coupling this module to `waters.navigation`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

EdgeKind = Literal[
    "same_reach",
    "downstream_of",
    "upstream_of",
    "same_municipality",
    "affects_municipality",
    "shares_disaster",
]


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: Literal["asset", "event"]
    label: str
    municipality: str | None = None
    asset_type: str | None = None
    vpuid: str | None = None


@dataclass(frozen=True)
class GraphEdge:
    from_id: str
    to_id: str
    kind: EdgeKind
    evidence: str
    weight: float = 1.0
    confidence: int = 80

    def model_dump(self) -> dict[str, Any]:
        return {
            "from": self.from_id,
            "to": self.to_id,
            "kind": self.kind,
            "weight": self.weight,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }


_DISASTER_RE = re.compile(r"_fema_(\d+)_pw")


def _disaster_number(event_id: str) -> str | None:
    m = _DISASTER_RE.search(event_id)
    return m.group(1) if m else None


def _normalize_municipality(value: str | None) -> str:
    return (value or "").strip().casefold()


def _asset_node(asset: dict[str, Any]) -> GraphNode:
    return GraphNode(
        id=asset["asset_id"],
        kind="asset",
        label=asset.get("asset_name", asset["asset_id"]),
        municipality=asset.get("municipality"),
        asset_type=asset.get("asset_type"),
        vpuid=asset.get("vpuid"),
    )


def _event_node(event: dict[str, Any]) -> GraphNode:
    return GraphNode(
        id=event["event_id"],
        kind="event",
        label=event.get("affected_area", event["event_id"]),
        municipality=_extract_event_municipality(event),
    )


def _extract_event_municipality(event: dict[str, Any]) -> str | None:
    """FEMA `affected_area` is shaped `'<County>, PR — <damage category>'`."""
    area = event.get("affected_area") or ""
    if "," in area:
        return area.split(",", 1)[0].strip()
    return None


def _stable_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _same_reach_edges(assets: list[dict[str, Any]]) -> list[GraphEdge]:
    by_reach: dict[str, list[dict[str, Any]]] = {}
    for a in assets:
        rc = a.get("reachcode")
        if rc:
            by_reach.setdefault(rc, []).append(a)
    edges: list[GraphEdge] = []
    for reachcode, group in by_reach.items():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                fro, to = _stable_pair(a["asset_id"], b["asset_id"])
                edges.append(
                    GraphEdge(
                        from_id=fro,
                        to_id=to,
                        kind="same_reach",
                        evidence=f"both snap to NHDPlus reachcode {reachcode}",
                        confidence=85,
                    )
                )
    return edges


def _same_municipality_edges(assets: list[dict[str, Any]]) -> list[GraphEdge]:
    by_muni: dict[str, list[dict[str, Any]]] = {}
    for a in assets:
        m = _normalize_municipality(a.get("municipality"))
        if m:
            by_muni.setdefault(m, []).append(a)
    edges: list[GraphEdge] = []
    for muni, group in by_muni.items():
        if len(group) < 2:
            continue
        muni_label = group[0].get("municipality", muni)
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                fro, to = _stable_pair(a["asset_id"], b["asset_id"])
                edges.append(
                    GraphEdge(
                        from_id=fro,
                        to_id=to,
                        kind="same_municipality",
                        evidence=f"both located in {muni_label}",
                        confidence=60,  # weaker than same_reach
                    )
                )
    return edges


def _affects_municipality_edges(
    assets: list[dict[str, Any]], events: list[dict[str, Any]]
) -> list[GraphEdge]:
    by_muni: dict[str, list[dict[str, Any]]] = {}
    for a in assets:
        m = _normalize_municipality(a.get("municipality"))
        if m:
            by_muni.setdefault(m, []).append(a)
    edges: list[GraphEdge] = []
    for ev in events:
        muni = _normalize_municipality(_extract_event_municipality(ev))
        if not muni:
            continue
        for asset in by_muni.get(muni, []):
            edges.append(
                GraphEdge(
                    from_id=ev["event_id"],
                    to_id=asset["asset_id"],
                    kind="affects_municipality",
                    evidence=f"event affects {ev.get('affected_area')}",
                    confidence=55,
                )
            )
    return edges


def _shares_disaster_edges(events: list[dict[str, Any]]) -> list[GraphEdge]:
    by_disaster: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        d = _disaster_number(ev["event_id"])
        if d:
            by_disaster.setdefault(d, []).append(ev)
    edges: list[GraphEdge] = []
    for disaster_number, group in by_disaster.items():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                fro, to = _stable_pair(a["event_id"], b["event_id"])
                edges.append(
                    GraphEdge(
                        from_id=fro,
                        to_id=to,
                        kind="shares_disaster",
                        evidence=f"both from FEMA disaster {disaster_number}",
                        confidence=90,
                    )
                )
    return edges


def _downstream_edges(
    assets: list[dict[str, Any]],
    nav_fn: Callable[[int, int], list[dict[str, Any]]],
    *,
    distance_km: int = 10,
) -> list[GraphEdge]:
    """For each asset's COMID, trace downstream; emit `downstream_of` edges to
    any other asset whose COMID appears in that trace.

    `nav_fn(comid, distance_km)` returns a list of downstream flowline dicts
    each carrying at least `{"comid": int}`. Injectable so tests stay offline.
    """
    edges: list[GraphEdge] = []
    by_comid: dict[int, dict[str, Any]] = {
        int(a["comid"]): a for a in assets if a.get("comid") is not None
    }
    for source in assets:
        src_comid = source.get("comid")
        if src_comid is None:
            continue
        try:
            downstream = nav_fn(int(src_comid), distance_km)
        except Exception:  # noqa: BLE001 — nav may raise; treat as no downstream
            continue
        for fl in downstream:
            comid = fl.get("comid") if isinstance(fl, dict) else getattr(fl, "comid", None)
            if comid is None or int(comid) == int(src_comid):
                continue
            sink = by_comid.get(int(comid))
            if sink is None:
                continue
            edges.append(
                GraphEdge(
                    from_id=sink["asset_id"],     # sink is downstream of source
                    to_id=source["asset_id"],
                    kind="downstream_of",
                    evidence=f"WATERS trace_downstream({src_comid}) hit comid={comid}",
                    confidence=85,
                )
            )
    return edges


def build_dependency_graph(
    *,
    assets: list[dict[str, Any]],
    events: list[dict[str, Any]],
    nav_fn: Callable[[int, int], list[dict[str, Any]]] | None = None,
    nav_distance_km: int = 10,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Build nodes + edges. When `nav_fn` is None, downstream edges are skipped
    (heuristic-only mode — fits demo runs without a WATERS API key).
    """
    nodes: list[GraphNode] = [_asset_node(a) for a in assets] + [_event_node(e) for e in events]
    edges: list[GraphEdge] = []
    edges.extend(_same_reach_edges(assets))
    edges.extend(_same_municipality_edges(assets))
    edges.extend(_affects_municipality_edges(assets, events))
    edges.extend(_shares_disaster_edges(events))
    if nav_fn is not None:
        edges.extend(_downstream_edges(assets, nav_fn, distance_km=nav_distance_km))
    return nodes, edges
