"""Hydro/network/raster analysis primitives for AguaYLuz.

The network functions are dependency-free and deterministic. RasterSpec is an
interface contract for COG/GeoTIFF/DEM layers; actual sampling is delegated to
rasterio/PostGIS adapters when the optional geo stack is installed.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict, deque
from typing import Iterable, Mapping, Sequence

@dataclass(frozen=True)
class DirectedEdge:
    upstream_id: str
    downstream_id: str
    relation: str = "FLOWS_TO"

@dataclass(frozen=True)
class RasterSpec:
    layer_id: str
    uri: str
    crs: str
    bbox: tuple[float,float,float,float]
    pixel_size_x: float
    pixel_size_y: float
    nodata: float | None = None
    band: int = 1
    source_authority: str = "UNKNOWN"
    logical_sha256: str | None = None
    def validate(self) -> None:
        if not self.crs: raise ValueError("raster CRS is required")
        if len(self.bbox) != 4 or self.bbox[0] > self.bbox[2] or self.bbox[1] > self.bbox[3]: raise ValueError("invalid raster bbox")
        if self.pixel_size_x <= 0 or self.pixel_size_y <= 0: raise ValueError("pixel sizes must be positive")
        if self.band < 1: raise ValueError("band is 1-based")

def _adjacency(edges: Iterable[DirectedEdge]) -> tuple[dict[str,set[str]],dict[str,set[str]]]:
    down: dict[str,set[str]] = defaultdict(set); up: dict[str,set[str]] = defaultdict(set)
    for e in edges:
        if e.upstream_id == e.downstream_id: continue
        down[e.upstream_id].add(e.downstream_id); up[e.downstream_id].add(e.upstream_id)
    return down, up

def trace_downstream(start_id: str, edges: Iterable[DirectedEdge], *, max_hops: int = 1000) -> list[str]:
    down,_ = _adjacency(edges); return _trace(start_id, down, max_hops)

def trace_upstream(start_id: str, edges: Iterable[DirectedEdge], *, max_hops: int = 1000) -> list[str]:
    _,up = _adjacency(edges); return _trace(start_id, up, max_hops)

def _trace(start_id: str, graph: Mapping[str,set[str]], max_hops: int) -> list[str]:
    if max_hops < 0: raise ValueError("max_hops must be non-negative")
    seen={start_id}; q=deque([(start_id,0)]); out=[]
    while q:
        node,depth=q.popleft()
        if depth >= max_hops: continue
        for nxt in sorted(graph.get(node,set())):
            if nxt in seen: continue
            seen.add(nxt); out.append(nxt); q.append((nxt,depth+1))
    return out

def impacted_assets(start_id: str, edges: Iterable[DirectedEdge], asset_to_segment: Mapping[str,str], *, direction: str="downstream") -> list[str]:
    trace = set(trace_downstream(start_id,edges) if direction=="downstream" else trace_upstream(start_id,edges)) | {start_id}
    return sorted(asset_id for asset_id,segment_id in asset_to_segment.items() if segment_id in trace)

def raster_layer_contract(spec: RasterSpec) -> dict:
    spec.validate()
    return {"layer_id":spec.layer_id,"geometry_types":["Raster"],"crs":spec.crs,"bbox":list(spec.bbox),"source_authority":spec.source_authority,"uri":spec.uri,"pixel_size":[spec.pixel_size_x,spec.pixel_size_y],"nodata":spec.nodata,"band":spec.band,"logical_sha256":spec.logical_sha256}
