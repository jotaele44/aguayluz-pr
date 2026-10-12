"""Spatial binding for the NWS hydromet plane (ingest-side only).

Needs shapely, which every full install already carries through ``pynhd``. The backend
never imports this module: it serves bindings the ingest already computed.

Evidence follows the hazard-advisory skill ranking. A point inside a municipio polygon
whose source-published municipio name agrees is ``POINT_IN_POLYGON_WITH_ALIAS``; a
point inside with no published name is ``POINT_IN_POLYGON``; a disagreement stays
``UNRESOLVED`` (the candidate is kept for review, never adopted). The Census
cartographic boundaries are generalized at the coast, so a river-mouth gauge can fall a
few hundred metres offshore: within :data:`COASTAL_SNAP_M` of a municipio whose name
the source also publishes, that is ``ALIAS_WITH_SPATIOTEMPORAL_SUPPORT`` with the
distance recorded; anything else stays ``UNRESOLVED``. Nothing is ever promoted to
island-wide.
"""
from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import DATA_DIR
from ..hazard_plane import EvidenceClass, SpatialState

MUNICIPIOS_GEOJSON = DATA_DIR / "geo" / "pr_municipios.geojson"

#: Largest gap (metres) between an offshore point and the municipio its source names.
COASTAL_SNAP_M = 1500.0


def municipio_key(name: Any) -> str:
    """Accent-insensitive, case-insensitive municipio name key."""
    folded = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    return " ".join(folded.casefold().split())


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Municipio:
    name: str
    geoid: str


@dataclass(frozen=True)
class PointBinding:
    """Outcome of binding one source point to a municipio."""

    geoid: str | None
    municipio: str | None
    evidence_class: EvidenceClass
    spatial_state: SpatialState
    method: str
    distance_m: float | None = None
    candidate_geoid: str | None = None
    candidate_municipio: str | None = None

    @property
    def bound(self) -> bool:
        return self.geoid is not None


class MunicipioIndex:
    """The 78 Census municipio polygons, prepared for point and polygon tests."""

    def __init__(self, features: list[dict[str, Any]]):
        from shapely.geometry import shape
        from shapely.prepared import prep

        self.municipios: list[Municipio] = []
        self._geoms: list[Any] = []
        self._prepared: list[Any] = []
        for feature in features:
            props = feature.get("properties") or {}
            name, geoid = props.get("name"), props.get("geoid")
            if not name or not geoid or not feature.get("geometry"):
                continue
            geom = shape(feature["geometry"])
            self.municipios.append(Municipio(name=str(name), geoid=str(geoid)))
            self._geoms.append(geom)
            self._prepared.append(prep(geom))
        self._by_key = {municipio_key(m.name): i for i, m in enumerate(self.municipios)}

    @classmethod
    def from_geojson(cls, path: Path | None = None) -> MunicipioIndex:
        doc = json.loads(Path(path or MUNICIPIOS_GEOJSON).read_text(encoding="utf-8"))
        return cls(doc.get("features", []))

    def by_name(self, name: Any) -> Municipio | None:
        index = self._by_key.get(municipio_key(name))
        return self.municipios[index] if index is not None else None

    def locate(self, lon: float, lat: float) -> Municipio | None:
        from shapely.geometry import Point

        point = Point(lon, lat)
        for municipio, prepared in zip(self.municipios, self._prepared, strict=True):
            if prepared.covers(point):
                return municipio
        return None

    def nearest(self, lon: float, lat: float) -> tuple[Municipio, float] | None:
        """Nearest municipio polygon and the geodesic gap to it in metres."""
        from shapely.geometry import Point
        from shapely.ops import nearest_points

        point = Point(lon, lat)
        best: tuple[Municipio, float] | None = None
        for municipio, geom in zip(self.municipios, self._geoms, strict=True):
            near = nearest_points(point, geom)[1]
            gap = _haversine_m(lon, lat, near.x, near.y)
            if best is None or gap < best[1]:
                best = (municipio, gap)
        return best

    def bind_point(self, lon: Any, lat: Any, alias: Any = None) -> PointBinding:
        """Bind a source point to a municipio, corroborated by the source's own name."""
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            return PointBinding(None, None, EvidenceClass.UNRESOLVED, SpatialState.NULL_EMPTY,
                                "no_coordinates")
        alias_key = municipio_key(alias)
        hit = self.locate(float(lon), float(lat))
        if hit is not None:
            if not alias_key:
                return PointBinding(hit.geoid, hit.name, EvidenceClass.POINT_IN_POLYGON,
                                    SpatialState.FULLY_WITHIN, "point_in_polygon")
            if alias_key == municipio_key(hit.name):
                return PointBinding(hit.geoid, hit.name, EvidenceClass.POINT_IN_POLYGON_WITH_ALIAS,
                                    SpatialState.FULLY_WITHIN, "point_in_polygon+source_alias")
            return PointBinding(None, None, EvidenceClass.UNRESOLVED, SpatialState.FULLY_WITHIN,
                                f"point_in_polygon_disagrees_with_source_alias:{alias}",
                                candidate_geoid=hit.geoid, candidate_municipio=hit.name)
        near = self.nearest(float(lon), float(lat))
        if near is not None and alias_key and alias_key == municipio_key(near[0].name):
            municipio, gap = near
            if gap <= COASTAL_SNAP_M:
                return PointBinding(municipio.geoid, municipio.name,
                                    EvidenceClass.ALIAS_WITH_SPATIOTEMPORAL_SUPPORT,
                                    SpatialState.OUTSIDE, "source_alias+nearest_polygon",
                                    distance_m=round(gap, 1))
        return PointBinding(None, None, EvidenceClass.UNRESOLVED, SpatialState.OUTSIDE,
                            "outside_every_municipio",
                            distance_m=round(near[1], 1) if near else None,
                            candidate_geoid=near[0].geoid if near else None,
                            candidate_municipio=near[0].name if near else None)


__all__ = [
    "COASTAL_SNAP_M",
    "MUNICIPIOS_GEOJSON",
    "Municipio",
    "MunicipioIndex",
    "PointBinding",
    "municipio_key",
]
