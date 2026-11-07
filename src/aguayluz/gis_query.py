"""Viewer-side GIS query primitives for the /gis/* API (gis-query/1.0).

Pure functions over GeoJSON features: parse an area of interest, test which
features fall inside it, identify features at a clicked point, rank text
search hits, filter by time, and serialise a selection for export.

Design rules:

* Stdlib only, so this module can be mirrored into the other PRII producers
  (moneysweep-pr, aguayluz-pr, skywatcher-pr, ovnis-pr) that do not carry
  shapely. Distances use :func:`federation.spatial_core.geodesic_distance_m`
  (Vincenty, WGS84); mirrors port that function alongside this file.
* The AOI vocabulary is the one in ``schemas/location_query.schema.json``
  (point / radius / bbox / polygon|geojson) so both APIs read the same JSON.
* Features without usable geometry, or without a parseable time when a time
  range is requested, are *counted* in ``excluded_count`` -- never silently
  dropped and never guessed.
* Results are COMPUTED spatial relations, not identity claims.

Geometry is PR-scoped: the antimeridian is not handled (bbox west must be
<= east). Edge-distance tests for lines/polygons use a local equirectangular
projection around the query centre, which is accurate to well under a metre
at the radii a map viewer uses (<= tens of km).
"""

from __future__ import annotations

import csv
import io
import math
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from aguayluz.gis_geodesy import geodesic_distance_m, validate_lon_lat

CONTRACT_QUERY = "gis-query/1.0"
QUERY_MODES = ("point", "radius", "bbox", "polygon")
DEFAULT_TOLERANCE_M = 25.0
MAX_LIMIT_PER_LAYER = 5000
_EARTH_RADIUS_M = 6371008.8
_CIRCLE_SEGMENTS = 64

Position = tuple[float, float]
Ring = tuple[Position, ...]
PolygonRings = tuple[Ring, ...]  # (outer, *holes)


class GisQueryError(ValueError):
    """A malformed AOI, time range or request parameter."""


# ─── Area of interest ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QueryArea:
    """A parsed AOI.

    ``mode`` is one of :data:`QUERY_MODES`. Point and radius areas are
    circles (point uses the tolerance as radius); bbox and polygon areas are
    stored as polygons. ``envelope`` is the lon/lat bounding box used for
    cheap prefiltering.
    """

    mode: str
    envelope: tuple[float, float, float, float]
    center: Position | None = None
    radius_m: float | None = None
    polygons: tuple[PolygonRings, ...] = ()

    @property
    def is_circle(self) -> bool:
        return self.center is not None and self.radius_m is not None


def _position(value: Any) -> Position:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise GisQueryError("a position must be [lon, lat]")
    try:
        lon, lat = validate_lon_lat(value[0], value[1])
    except (TypeError, ValueError) as exc:
        raise GisQueryError(str(exc)) from exc
    return lon, lat


def _ring(value: Any) -> Ring:
    if not isinstance(value, (list, tuple)):
        raise GisQueryError("a polygon ring must be an array of positions")
    points = [_position(p) for p in value]
    if len(points) >= 1 and points[0] != points[-1]:
        points.append(points[0])
    if len(points) < 4:
        raise GisQueryError("a polygon ring needs at least 3 distinct positions")
    return tuple(points)


def _polygon_from_geojson(geojson: Mapping[str, Any]) -> tuple[PolygonRings, ...]:
    if not isinstance(geojson, Mapping):
        raise GisQueryError("polygon geometry must be a GeoJSON object")
    kind = geojson.get("type")
    if kind == "Feature":
        return _polygon_from_geojson(geojson.get("geometry") or {})
    if kind == "Polygon":
        rings = geojson.get("coordinates")
        if not isinstance(rings, list) or not rings:
            raise GisQueryError("Polygon needs coordinates")
        return (tuple(_ring(r) for r in rings),)
    if kind == "MultiPolygon":
        polys = geojson.get("coordinates")
        if not isinstance(polys, list) or not polys:
            raise GisQueryError("MultiPolygon needs coordinates")
        out = []
        for rings in polys:
            if not isinstance(rings, list) or not rings:
                raise GisQueryError("MultiPolygon member needs rings")
            out.append(tuple(_ring(r) for r in rings))
        return tuple(out)
    raise GisQueryError(
        "polygon AOI must be a GeoJSON Polygon, MultiPolygon or Feature of one"
    )


def _envelope_of_polygons(
    polygons: Iterable[PolygonRings],
) -> tuple[float, float, float, float]:
    lons: list[float] = []
    lats: list[float] = []
    for rings in polygons:
        for lon, lat in rings[0]:
            lons.append(lon)
            lats.append(lat)
    return min(lons), min(lats), max(lons), max(lats)


def _destination(
    lon: float, lat: float, bearing_rad: float, distance_m: float
) -> Position:
    """Spherical forward geodesic -- only used to build circle envelopes/rings."""
    d = distance_m / _EARTH_RADIUS_M
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(
        math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(bearing_rad)
    )
    l2 = l1 + math.atan2(
        math.sin(bearing_rad) * math.sin(d) * math.cos(p1),
        math.cos(d) - math.sin(p1) * math.sin(p2),
    )
    return (math.degrees(l2) + 540) % 360 - 180, math.degrees(p2)


def _number(value: Any) -> float:
    """``float(value)``; a missing or non-numeric value raises TypeError/ValueError."""
    if isinstance(value, bool):
        raise TypeError("a coordinate must be a number, not a boolean")
    return float(value)


def circle_ring(
    lon: float, lat: float, radius_m: float, segments: int = _CIRCLE_SEGMENTS
) -> Ring:
    pts = [
        _destination(lon, lat, 2 * math.pi * i / segments, radius_m)
        for i in range(segments)
    ]
    pts.append(pts[0])
    return tuple(pts)


def parse_geometry(
    geometry: Mapping[str, Any], *, tolerance_m: float = DEFAULT_TOLERANCE_M
) -> QueryArea:
    """Parse a location_query-shaped AOI into a :class:`QueryArea`."""
    if not isinstance(geometry, Mapping):
        raise GisQueryError("geometry must be an object")
    kind = geometry.get("type")
    if kind in ("point", "radius"):
        try:
            lon, lat = validate_lon_lat(
                _number(geometry.get("lon")), _number(geometry.get("lat"))
            )
        except (TypeError, ValueError) as exc:
            raise GisQueryError(f"invalid {kind} centre: {exc}") from exc
        if kind == "radius":
            radius = geometry.get("radius_m")
            if (
                not isinstance(radius, (int, float))
                or not math.isfinite(radius)
                or radius <= 0
            ):
                raise GisQueryError("radius_m must be a positive number")
        else:
            radius = tolerance_m
            if not math.isfinite(radius) or radius <= 0:
                raise GisQueryError("tolerance_m must be positive")
        ring = circle_ring(lon, lat, float(radius))
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        return QueryArea(
            mode=kind,
            envelope=(min(lons), min(lats), max(lons), max(lats)),
            center=(lon, lat),
            radius_m=float(radius),
        )
    if kind == "bbox":
        try:
            west, south = validate_lon_lat(
                _number(geometry.get("west")), _number(geometry.get("south"))
            )
            east, north = validate_lon_lat(
                _number(geometry.get("east")), _number(geometry.get("north"))
            )
        except (TypeError, ValueError) as exc:
            raise GisQueryError(f"invalid bbox: {exc}") from exc
        if west > east or south > north:
            raise GisQueryError(
                "bbox requires west <= east and south <= north (antimeridian not supported)"
            )
        ring = (
            (west, south),
            (east, south),
            (east, north),
            (west, north),
            (west, south),
        )
        return QueryArea(
            mode="bbox", envelope=(west, south, east, north), polygons=((ring,),)
        )
    if kind in ("polygon", "geojson"):
        polygons = _polygon_from_geojson(geometry.get("geojson") or {})
        return QueryArea(
            mode="polygon", envelope=_envelope_of_polygons(polygons), polygons=polygons
        )
    raise GisQueryError(
        f"unsupported geometry type {kind!r}; expected one of {QUERY_MODES}"
    )


# ─── Feature geometry ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FeatureParts:
    points: tuple[Position, ...] = ()
    lines: tuple[tuple[Position, ...], ...] = ()
    polygons: tuple[PolygonRings, ...] = ()

    def is_empty(self) -> bool:
        return not (self.points or self.lines or self.polygons)

    def envelope(self) -> tuple[float, float, float, float]:
        lons: list[float] = []
        lats: list[float] = []
        for lon, lat in self.points:
            lons.append(lon)
            lats.append(lat)
        for line in self.lines:
            for lon, lat in line:
                lons.append(lon)
                lats.append(lat)
        for rings in self.polygons:
            for lon, lat in rings[0]:
                lons.append(lon)
                lats.append(lat)
        return min(lons), min(lats), max(lons), max(lats)


def _collect(
    geometry: Mapping[str, Any], points: list, lines: list, polygons: list
) -> None:
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "Point":
        points.append(_position(coords))
    elif kind == "MultiPoint":
        points.extend(_position(c) for c in coords or [])
    elif kind == "LineString":
        line = tuple(_position(c) for c in coords or [])
        if len(line) < 2:
            raise GisQueryError("LineString needs two positions")
        lines.append(line)
    elif kind == "MultiLineString":
        for member in coords or []:
            line = tuple(_position(c) for c in member or [])
            if len(line) < 2:
                raise GisQueryError("LineString needs two positions")
            lines.append(line)
    elif kind in ("Polygon", "MultiPolygon"):
        polygons.extend(_polygon_from_geojson(geometry))
    elif kind == "GeometryCollection":
        for member in geometry.get("geometries") or []:
            if isinstance(member, Mapping):
                _collect(member, points, lines, polygons)
    else:
        raise GisQueryError(f"unsupported feature geometry {kind!r}")


def feature_parts(feature: Mapping[str, Any]) -> FeatureParts | None:
    """Decompose a GeoJSON feature; ``None`` when it has no usable geometry."""
    geometry = feature.get("geometry") if isinstance(feature, Mapping) else None
    if not isinstance(geometry, Mapping):
        return None
    points: list[Position] = []
    lines: list[tuple[Position, ...]] = []
    polygons: list[PolygonRings] = []
    try:
        _collect(geometry, points, lines, polygons)
    except (GisQueryError, TypeError, ValueError):
        return None
    parts = FeatureParts(tuple(points), tuple(lines), tuple(polygons))
    return None if parts.is_empty() else parts


def feature_bbox(feature: Mapping[str, Any]) -> list[float] | None:
    parts = feature_parts(feature)
    return list(parts.envelope()) if parts else None


def feature_anchor(feature: Mapping[str, Any]) -> list[float] | None:
    """A representative [lon, lat]: the point itself, else the envelope centre."""
    parts = feature_parts(feature)
    if parts is None:
        return None
    if len(parts.points) == 1 and not parts.lines and not parts.polygons:
        return list(parts.points[0])
    w, s, e, n = parts.envelope()
    return [(w + e) / 2, (s + n) / 2]


# ─── Planar helpers ───────────────────────────────────────────────────────────


def _point_on_segment(
    p: Position, a: Position, b: Position, eps: float = 1e-12
) -> bool:
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    if abs(cross) > eps:
        return False
    return (
        min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
        and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps
    )


def _point_in_ring(p: Position, ring: Ring) -> bool:
    """Ray casting; points on the boundary count as inside (inclusive)."""
    inside = False
    x, y = p
    for i in range(len(ring) - 1):
        a, b = ring[i], ring[i + 1]
        if _point_on_segment(p, a, b):
            return True
        if (a[1] > y) != (b[1] > y):
            x_cross = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < x_cross:
                inside = not inside
    return inside


def point_in_polygon(p: Position, rings: PolygonRings) -> bool:
    if not _point_in_ring(p, rings[0]):
        return False
    for hole in rings[1:]:
        if _point_in_ring(p, hole) and not any(
            _point_on_segment(p, hole[i], hole[i + 1]) for i in range(len(hole) - 1)
        ):
            return False
    return True


def _orient(a: Position, b: Position, c: Position) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(p1: Position, p2: Position, q1: Position, q2: Position) -> bool:
    d1, d2 = _orient(q1, q2, p1), _orient(q1, q2, p2)
    d3, d4 = _orient(p1, p2, q1), _orient(p1, p2, q2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return True
    return (
        _point_on_segment(p1, q1, q2)
        or _point_on_segment(p2, q1, q2)
        or _point_on_segment(q1, p1, p2)
        or _point_on_segment(q2, p1, p2)
    )


def _segments(path: Sequence[Position]) -> Iterator[tuple[Position, Position]]:
    for i in range(len(path) - 1):
        yield path[i], path[i + 1]


def _local_xy(p: Position, origin: Position) -> tuple[float, float]:
    k = math.pi / 180 * _EARTH_RADIUS_M
    return (p[0] - origin[0]) * k * math.cos(math.radians(origin[1])), (
        p[1] - origin[1]
    ) * k


def _distance_to_segment_m(center: Position, a: Position, b: Position) -> float:
    ax, ay = _local_xy(a, center)
    bx, by = _local_xy(b, center)
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    t = 0.0 if seg_len2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg_len2))
    return math.hypot(ax + t * dx, ay + t * dy)


def _envelopes_overlap(a: Sequence[float], b: Sequence[float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


# ─── Predicates ───────────────────────────────────────────────────────────────


def distance_to_parts_m(center: Position, parts: FeatureParts) -> float:
    """Distance (m) from ``center`` to the nearest part; 0 inside a polygon."""
    best = math.inf
    for p in parts.points:
        best = min(best, geodesic_distance_m(center[0], center[1], p[0], p[1]))
    for line in parts.lines:
        for a, b in _segments(line):
            best = min(best, _distance_to_segment_m(center, a, b))
    for rings in parts.polygons:
        if point_in_polygon(center, rings):
            return 0.0
        for ring in rings:
            for a, b in _segments(ring):
                best = min(best, _distance_to_segment_m(center, a, b))
    return best


def _area_contains(area: QueryArea, p: Position) -> bool:
    return any(point_in_polygon(p, rings) for rings in area.polygons)


def _area_edges(area: QueryArea) -> Iterator[tuple[Position, Position]]:
    for rings in area.polygons:
        for ring in rings:
            yield from _segments(ring)


def intersects(parts: FeatureParts, area: QueryArea) -> bool:
    """True when any part of the feature touches the AOI (boundary inclusive)."""
    if not _envelopes_overlap(parts.envelope(), area.envelope):
        return False
    if area.is_circle:
        assert area.center is not None and area.radius_m is not None
        return distance_to_parts_m(area.center, parts) <= area.radius_m
    if any(_area_contains(area, p) for p in parts.points):
        return True
    for line in parts.lines:
        if any(_area_contains(area, p) for p in line):
            return True
        for a, b in _segments(line):
            if any(segments_intersect(a, b, c, d) for c, d in _area_edges(area)):
                return True
    for rings in parts.polygons:
        if any(_area_contains(area, p) for p in rings[0]):
            return True
        for area_rings in area.polygons:
            if point_in_polygon(area_rings[0][0], rings):
                return True
        for ring in rings:
            for a, b in _segments(ring):
                if any(segments_intersect(a, b, c, d) for c, d in _area_edges(area)):
                    return True
    return False


# ─── Time ─────────────────────────────────────────────────────────────────────

_TIME_RE = re.compile(
    r"^(?P<y>\d{4})(?:-(?P<m>\d{2})(?:-(?P<d>\d{2})(?:[T ](?P<H>\d{2}):(?P<M>\d{2})(?::(?P<S>\d{2}))?)?)?)?"
)


def normalize_time(value: Any, *, upper: bool = False) -> str | None:
    """Comparable 'YYYY-MM-DDTHH:MM:SS' key; partial dates expand to the start
    (or, with ``upper``, the end) of the period. ``None`` if unparseable."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(int(value))
    if not isinstance(value, str):
        return None
    match = _TIME_RE.match(value.strip())
    if not match:
        return None
    y = match.group("y")
    m = match.group("m") or ("12" if upper else "01")
    if match.group("d"):
        d = match.group("d")
    elif upper:
        month = int(m)
        if not 1 <= month <= 12:
            return None
        d = f"{(31 if month in (1, 3, 5, 7, 8, 10, 12) else 30 if month != 2 else 29):02d}"
    else:
        d = "01"
    hh = match.group("H") or ("23" if upper else "00")
    mm = match.group("M") or ("59" if upper else "00")
    ss = match.group("S") or ("59" if upper else "00")
    if not (1 <= int(m) <= 12 and 1 <= int(d) <= 31):
        return None
    return f"{y}-{m}-{d}T{hh}:{mm}:{ss}"


def parse_time_range(
    time_range: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    if not time_range:
        return None, None
    start_raw, end_raw = time_range.get("start"), time_range.get("end")
    start = normalize_time(start_raw) if start_raw else None
    end = normalize_time(end_raw, upper=True) if end_raw else None
    if start_raw and start is None:
        raise GisQueryError(f"unparseable time_range.start {start_raw!r}")
    if end_raw and end is None:
        raise GisQueryError(f"unparseable time_range.end {end_raw!r}")
    if start and end and start > end:
        raise GisQueryError("time_range.start is after time_range.end")
    return start, end


def _in_time(
    props: Mapping[str, Any], field: str, start: str | None, end: str | None
) -> bool | None:
    key = normalize_time(props.get(field))
    if key is None:
        return None
    if start and key < start:
        return False
    return not (end and key > end)


# ─── Query / identify / search ────────────────────────────────────────────────


def feature_identifier(
    feature: Mapping[str, Any], id_fields: Sequence[str] = ()
) -> str | None:
    if feature.get("id") not in (None, ""):
        return str(feature["id"])
    props = feature.get("properties") or {}
    for key in (
        *id_fields,
        "feature_id",
        "canonical_id",
        "id",
        "GEOID",
        "objectid",
        "nid_id",
    ):
        value = props.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def query_layer(
    layer_id: str,
    features: Sequence[Mapping[str, Any]],
    area: QueryArea,
    *,
    temporal_field: str | None = None,
    time_range: tuple[str | None, str | None] = (None, None),
    limit: int = 500,
) -> dict[str, Any]:
    """Run one AOI against one layer; returns a gis-query/1.0 layer_result."""
    if not 1 <= limit <= MAX_LIMIT_PER_LAYER:
        raise GisQueryError(f"limit_per_layer must be 1..{MAX_LIMIT_PER_LAYER}")
    start, end = time_range
    timed = bool(temporal_field and (start or end))
    matched: list[Mapping[str, Any]] = []
    excluded = 0
    for feature in features:
        parts = feature_parts(feature)
        if parts is None:
            excluded += 1
            continue
        if timed:
            assert temporal_field is not None
            ok = _in_time(feature.get("properties") or {}, temporal_field, start, end)
            if ok is None:
                excluded += 1
                continue
            if not ok:
                continue
        if intersects(parts, area):
            matched.append(feature)
    returned = matched[:limit]
    return {
        "layer_id": layer_id,
        "matched_count": len(matched),
        "returned_count": len(returned),
        "excluded_count": excluded,
        "truncated": len(matched) > limit,
        "error": None,
        "features": [dict(f) for f in returned],
    }


def identify(
    features: Sequence[Mapping[str, Any]],
    lon: float,
    lat: float,
    *,
    tolerance_m: float = DEFAULT_TOLERANCE_M,
    limit: int = 10,
) -> list[tuple[float, Mapping[str, Any]]]:
    """Features within ``tolerance_m`` of the point, nearest first."""
    try:
        center = validate_lon_lat(lon, lat)
    except (TypeError, ValueError) as exc:
        raise GisQueryError(str(exc)) from exc
    area = parse_geometry(
        {"type": "point", "lon": center[0], "lat": center[1]}, tolerance_m=tolerance_m
    )
    hits: list[tuple[float, Mapping[str, Any]]] = []
    for feature in features:
        parts = feature_parts(feature)
        if parts is None or not _envelopes_overlap(parts.envelope(), area.envelope):
            continue
        distance = distance_to_parts_m(center, parts)
        if distance <= tolerance_m:
            hits.append((distance, feature))
    hits.sort(key=lambda item: item[0])
    return hits[:limit]


def fold_text(value: Any) -> str:
    """Case- and accent-insensitive comparison key ('Mayagüez' -> 'mayaguez')."""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().casefold()


def search_features(
    features: Sequence[Mapping[str, Any]],
    query: str,
    fields: Sequence[str],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Rank features whose ``fields`` match ``query``.

    Rank 0 exact, 1 prefix, 2 word prefix, 3 substring; ties keep input order.
    """
    needle = fold_text(query)
    if not needle or not fields:
        return []
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, feature in enumerate(features):
        props = feature.get("properties") or {}
        best: tuple[int, str, str] | None = None
        for field in fields:
            raw = props.get(field)
            if raw in (None, ""):
                continue
            hay = fold_text(raw)
            if hay == needle:
                rank = 0
            elif hay.startswith(needle):
                rank = 1
            elif any(word.startswith(needle) for word in hay.split(" ")):
                rank = 2
            elif needle in hay:
                rank = 3
            else:
                continue
            if best is None or rank < best[0]:
                best = (rank, field, str(raw))
        if best is not None:
            ranked.append(
                (
                    best[0],
                    index,
                    {
                        "feature": feature,
                        "rank": best[0],
                        "field": best[1],
                        "value": best[2],
                    },
                )
            )
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked[:limit]]


# Coordinate parsing is linear-time by construction (the text is typed by a
# user): decimal pairs are split on one separator class and each token is
# full-matched; DMS is matched only after all whitespace is removed, against a
# pattern whose quantifiers are all bounded. Nothing longer than a coordinate
# could plausibly be is parsed at all.
MAX_COORDINATE_TEXT = 64
_SEPARATORS_RE = re.compile(r"[\s,;]+")
_DECIMAL_RE = re.compile(r"[+-]?\d{1,3}(?:\.\d{1,12})?")
_DMS_PART = (
    r"(\d{1,3})[°d](?:(\d{1,2}(?:\.\d{1,6})?)['′m])?"
    r"(?:(\d{1,2}(?:\.\d{1,6})?)(?:\"|″|''|s))?([NSEWnsew])"
)
_DMS_RE = re.compile(rf"{_DMS_PART}[,;]?{_DMS_PART}")
_WHITESPACE_RE = re.compile(r"\s+")


def _dms_value(
    deg: str, minutes: str | None, seconds: str | None, hemi: str
) -> tuple[float, str]:
    value = float(deg) + float(minutes or 0) / 60 + float(seconds or 0) / 3600
    hemi = hemi.upper()
    return (-value if hemi in ("S", "W") else value), hemi


PR_REGION = (
    -68.5,
    17.5,
    -64.5,
    19.0,
)  # lon/lat envelope used to disambiguate typed pairs


def parse_coordinate_text(
    text: str, *, prefer_region: Sequence[float] = PR_REGION
) -> Position | None:
    """Parse a typed coordinate into (lon, lat), or ``None``.

    Accepts decimal degrees in either order and DMS with hemisphere letters,
    e.g. ``18°28'20"N 66°42'56"W``. A bare decimal pair is read as
    ``lat, lon`` (map-search convention) unless only the reverse reading
    falls inside ``prefer_region``; if neither reading is in the region, the
    first valid reading wins.
    """
    text = (text or "").strip()
    if not text or len(text) > MAX_COORDINATE_TEXT:
        return None
    tokens = [token for token in _SEPARATORS_RE.split(text) if token]
    if len(tokens) == 2 and all(_DECIMAL_RE.fullmatch(token) for token in tokens):
        a, b = float(tokens[0]), float(tokens[1])
        readings: list[Position] = []
        for lat, lon in ((a, b), (b, a)):
            try:
                readings.append(validate_lon_lat(lon, lat))
            except ValueError:
                continue
        if not readings:
            return None
        west, south, east, north = prefer_region
        in_region = [
            r for r in readings if west <= r[0] <= east and south <= r[1] <= north
        ]
        return (in_region or readings)[0]
    match = _DMS_RE.fullmatch(_WHITESPACE_RE.sub("", text))
    if match:
        first, h1 = _dms_value(*match.group(1, 2, 3, 4))
        second, h2 = _dms_value(*match.group(5, 6, 7, 8))
        if h1 in "NS" and h2 in "EW":
            lat, lon = first, second
        elif h1 in "EW" and h2 in "NS":
            lon, lat = first, second
        else:
            return None
        try:
            return validate_lon_lat(lon, lat)
        except ValueError:
            return None
    return None


def summarize(
    features: Iterable[Mapping[str, Any]], fields: Sequence[str]
) -> dict[str, dict[str, int]]:
    """Value counts per field -- the generic building block of domain summaries."""
    summary: dict[str, dict[str, int]] = {field: {} for field in fields}
    for feature in features:
        props = feature.get("properties") or {}
        for field in fields:
            value = props.get(field)
            key = "(missing)" if value in (None, "") else str(value)
            summary[field][key] = summary[field].get(key, 0) + 1
    return {
        field: dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
        for field, counts in summary.items()
    }


def features_to_csv(
    features: Sequence[Mapping[str, Any]], *, id_fields: Sequence[str] = ()
) -> str:
    """CSV with feature_id, anchor lon/lat, geometry type and every property."""
    columns: list[str] = []
    for feature in features:
        for key in feature.get("properties") or {}:
            if key not in columns:
                columns.append(key)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        ["feature_id", "anchor_lon", "anchor_lat", "geometry_type", *columns]
    )
    for feature in features:
        props = feature.get("properties") or {}
        anchor = feature_anchor(feature)
        geometry = feature.get("geometry") or {}
        writer.writerow(
            [
                feature_identifier(feature, id_fields) or "",
                "" if anchor is None else round(anchor[0], 7),
                "" if anchor is None else round(anchor[1], 7),
                geometry.get("type", "") if isinstance(geometry, Mapping) else "",
                *["" if props.get(c) is None else props.get(c) for c in columns],
            ]
        )
    return buffer.getvalue()
