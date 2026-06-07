"""HIFLD (Homeland Infrastructure Foundation-Level Data) adapter.

Public source: HIFLD layers hosted on ArcGIS REST FeatureServer endpoints.
Schema differs per layer but the common shape is a GeoJSON FeatureCollection:
  {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": ..., "properties": ...}]}

HIFLD's value vs. FRS: HIFLD carries geometry for line assets (transmission
lines, distribution pipes) that FRS's point-only registry doesn't have.
Points become snap coords directly; lines and polygons get the *centroid* as
the snap coord, but `geometry_type="line"`/"polygon" propagates to the asset
so downstream consumers know the source shape.

Property normalization: HIFLD layer property names vary (NAME vs FACILITY vs
PLANTNAME). We try a fixed list of candidates and fall back to the OBJECTID.
"""

from __future__ import annotations

from typing import Any

from ..models import GeometryType
from .frs import infer_asset_type
from .pipeline import FacilitySeed

HIFLD_PROVENANCE = "HIFLD ArcGIS FeatureServer (GeoJSON)"

# Property keys HIFLD layers use for the facility name, in priority order.
_NAME_KEYS = ("NAME", "FACILITY", "FACNAME", "PLANTNAME", "STATION_NAME", "OBJECT_NAME")
_OPERATOR_KEYS = ("OWNER", "OPERATOR", "AGENCY", "COMPANY")
_MUNICIPALITY_KEYS = ("CITY", "MUNICIPALITY", "PLACE", "TOWN")
_STATE_KEYS = ("STATE", "ST_ABBR", "STATE_ABBR")
_ID_KEYS = ("ID", "OBJECTID", "FACILITYID", "GLOBALID")


def _pick(properties: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in properties and properties[key]:
            return str(properties[key]).strip()
    return None


def _centroid_point(coords: list[Any]) -> tuple[float, float]:
    """Mean of (lon, lat) pairs in a flat coordinate list."""
    if not coords:
        return (0.0, 0.0)
    lons = [float(c[0]) for c in coords]
    lats = [float(c[1]) for c in coords]
    return (sum(lons) / len(lons), sum(lats) / len(lats))


def _snap_coords_from_geometry(geom: dict[str, Any]) -> tuple[GeometryType, float | None, float | None]:
    """Return `(geometry_type, lon, lat)` extracted from a GeoJSON geometry.

    For lines and polygons we use the centroid as the snap coord — close enough
    for NHDPlus point-indexing on infrastructure assets, and the source shape
    is preserved in `geometry_type` for downstream consumers.
    """
    if not isinstance(geom, dict):
        return ("unknown", None, None)
    gtype = (geom.get("type") or "").lower()
    coords = geom.get("coordinates")
    if not coords:
        return ("unknown", None, None)
    try:
        if gtype == "point":
            return ("point", float(coords[0]), float(coords[1]))
        if gtype == "linestring":
            lon, lat = _centroid_point(coords)
            return ("line", lon, lat)
        if gtype == "multilinestring":
            flat: list[Any] = []
            for line in coords:
                flat.extend(line)
            lon, lat = _centroid_point(flat)
            return ("line", lon, lat)
        if gtype == "polygon":
            lon, lat = _centroid_point(coords[0])
            return ("polygon", lon, lat)
        if gtype == "multipolygon":
            flat = []
            for poly in coords:
                flat.extend(poly[0])
            lon, lat = _centroid_point(flat)
            return ("polygon", lon, lat)
    except (TypeError, ValueError, IndexError):
        return ("unknown", None, None)
    return ("unknown", None, None)


def parse_hifld_geojson(
    geojson: dict[str, Any],
    *,
    state_filter: str | None = "PR",
) -> list[FacilitySeed]:
    """Parse a HIFLD GeoJSON FeatureCollection into FacilitySeed records.

    `state_filter`: if set, drops features whose STATE property doesn't match
    (case-insensitive). Pass None to skip filtering — useful for hand-curated
    fixtures that don't carry a STATE property.
    """
    features = geojson.get("features", []) or []
    seeds: list[FacilitySeed] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        properties = feat.get("properties") or {}
        geom = feat.get("geometry") or {}

        # Optional state filter — HIFLD layers serve nationwide data.
        if state_filter is not None:
            state = _pick(properties, _STATE_KEYS)
            if state and state.strip().upper() != state_filter.upper():
                continue

        name = _pick(properties, _NAME_KEYS) or _pick(properties, _ID_KEYS) or "Unknown HIFLD asset"
        municipality = _pick(properties, _MUNICIPALITY_KEYS) or "Unknown"
        feature_id = _pick(properties, _ID_KEYS) or name.replace(" ", "_")

        asset_type, asset_subtype, is_utility = infer_asset_type(name)
        geometry_type, lon, lat = _snap_coords_from_geometry(geom)

        seeds.append(
            FacilitySeed(
                seed_id=f"AYL_AST_HIFLD_{feature_id}",
                name=name,
                municipality=municipality.title() if municipality else "Unknown",
                asset_type=asset_type,
                asset_subtype=asset_subtype,
                lat=lat,
                lon=lon,
                operator=_pick(properties, _OPERATOR_KEYS),
                source_provenance=f"{HIFLD_PROVENANCE} id={feature_id}",
                is_utility=is_utility,
                geometry_type=geometry_type,
            )
        )
    return seeds
