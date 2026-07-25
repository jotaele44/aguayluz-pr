"""Infrastructure-impact linkage for promoted alerts.

Every promoter (:mod:`aguayluz.water_alerts` + the ``alert_promotion`` package) turns a
raw signal into an :class:`~aguayluz.alerts.AlertEvent`, but historically left
``sectors_impacted=[]`` and ``linked_asset_ids`` untouched — so an alert never named the
water / power infrastructure it actually threatens, which is the whole point of this
producer.

This module closes that gap with two pure helpers that map an alert's location to the
producer's own ``data/utility_assets.jsonl`` corpus:

* :func:`build_asset_index` — pre-indexes the assets once (a geocoded list for radius
  matching + a municipality bucket for the no-coordinate fallback).
* :func:`link_impact` — for one alert, returns the affected ``(linked_asset_ids,
  sectors_impacted)``.

Pure functions only (no I/O, no wall-clock). The CLI (``scripts/build_alerts.py``) loads
the assets and builds the index; the promoters call :func:`link_impact`.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field
from typing import Any


def _geo_key(name: Any) -> str:
    """unaccent + upper municipality key. Mirrors ``water_alerts._geo_key`` — kept local
    so this module has no dependency back on ``water_alerts`` (which imports linkage)."""
    folded = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return " ".join(folded.upper().split())

#: Map a utility ``asset_type`` to its dashboard/federation sector key. Aligned with
#: ``server/backend/main.py`` ``SECTOR_TYPE_MAP`` and ``dashboard/src/lib/sectors.js``
#: ``SECTOR_META`` so the derived ``sectors_impacted`` renders on the sector cards with no
#: downstream change. Kept deliberately small — the corpus only carries these three types.
SECTOR_FOR_ASSET_TYPE: dict[str, str] = {
    "water": "water",
    "wastewater": "wastewater",
    "power": "power",
}

#: Per-module default search radius (km) for :func:`link_impact`. ``None`` forces the
#: municipality-bucket path — the right choice for every area-based source (NWS hazards,
#: SDWIS/OSHA rows carry only a municipality, not a true point). Only seismic alerts have
#: a real epicenter, so only they radiate over a radius; the quake band spans PR-scale
#: distances, hence ~25 km.
MODULE_RADIUS_KM: dict[str, float | None] = {
    "SEISMIC_GEO": 25.0,
    "INDUSTRIAL": None,
    "WEATHER_HAZARD": None,
    "CONTAMINATION": None,
    "HYDRO_OPS": None,
}

#: Cap on how many assets a single alert links, so a broad hazard over a dense water
#: network does not attach thousands of ids. Sectors are unaffected by this cap.
DEFAULT_MAX_ASSETS = 50

# ``alert_event`` schema latitude/longitude bounds (PR mainland + Vieques + Culebra +
# Mona). A source coordinate outside this box (e.g. an offshore epicenter) cannot be
# stored on an AlertEvent, so callers fall back to a centroid rather than clamping.
ALERT_LAT_MIN, ALERT_LAT_MAX = 17.7, 18.7
ALERT_LON_MIN, ALERT_LON_MAX = -67.95, -65.2


def in_alert_bounds(lat: Any, lon: Any) -> bool:
    """True when ``lat``/``lon`` are numeric and inside the ``alert_event`` PR bounds."""
    return (
        isinstance(lat, (int, float))
        and isinstance(lon, (int, float))
        and ALERT_LAT_MIN <= lat <= ALERT_LAT_MAX
        and ALERT_LON_MIN <= lon <= ALERT_LON_MAX
    )


def merge_asset_ids(existing: list[str] | None, derived: list[str] | None) -> list[str]:
    """Union of ids an event already carried and ones linkage derived — sorted, unique."""
    return sorted({str(x) for x in (existing or [])} | {str(x) for x in (derived or [])})


@dataclass(frozen=True)
class AssetIndex:
    """Pre-computed lookups over ``data/utility_assets.jsonl`` for alert linkage."""

    #: ``(asset_id, asset_type, lat, lon)`` for every asset carrying usable coordinates.
    geocoded: list[tuple[str, str, float, float]] = field(default_factory=list)
    #: ``_geo_key(municipality) -> [(asset_id, asset_type), ...]`` for the fallback path.
    by_municipality: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in kilometres."""
    r = 6371.0088  # mean Earth radius (km)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def build_asset_index(assets: list[dict[str, Any]]) -> AssetIndex:
    """Index utility assets by coordinate and by municipality for alert linkage."""
    geocoded: list[tuple[str, str, float, float]] = []
    by_municipality: dict[str, list[tuple[str, str]]] = {}
    for a in assets:
        asset_id = a.get("asset_id")
        asset_type = a.get("asset_type")
        if not asset_id or asset_type not in SECTOR_FOR_ASSET_TYPE:
            continue
        lat, lon = a.get("lat"), a.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            geocoded.append((str(asset_id), str(asset_type), float(lat), float(lon)))
        muni = a.get("municipality")
        key = _geo_key(muni) if muni else ""
        # "Puerto Rico" is the catch-all placeholder municipality — not a real bucket.
        if key and key != "PUERTO RICO":
            by_municipality.setdefault(key, []).append((str(asset_id), str(asset_type)))
    return AssetIndex(geocoded=geocoded, by_municipality=by_municipality)


def _sectors_for(asset_types: set[str]) -> list[str]:
    """Sorted, unique sector keys for a set of asset types."""
    return sorted({SECTOR_FOR_ASSET_TYPE[t] for t in asset_types if t in SECTOR_FOR_ASSET_TYPE})


def link_impact(
    lat: float | None,
    lon: float | None,
    municipalities: list[str] | None,
    index: AssetIndex,
    *,
    radius_km: float | None,
    max_assets: int = DEFAULT_MAX_ASSETS,
) -> tuple[list[str], list[str]]:
    """Resolve the infrastructure an alert affects.

    Returns ``(linked_asset_ids, sectors_impacted)`` — both deterministic:
    ``linked_asset_ids`` sorted then capped at ``max_assets``, ``sectors_impacted`` the
    sorted unique sector keys of *all* matched assets (never capped). No match, an empty
    index, or missing inputs all yield ``([], [])``.

    A coordinate radius match is used when ``lat``/``lon`` and ``radius_km`` are all
    present; otherwise the alert's municipalities select the assets. Sectors are derived
    from the full match set even when the id list is capped, so a broad hazard still
    reports every sector it touches.
    """
    matches: list[tuple[str, str]] = []

    if lat is not None and lon is not None and radius_km is not None:
        for asset_id, asset_type, alat, alon in index.geocoded:
            if _haversine_km(lat, lon, alat, alon) <= radius_km:
                matches.append((asset_id, asset_type))
    else:
        for muni in municipalities or []:
            key = _geo_key(muni)
            if key and key != "(UNSCOPED)":
                matches.extend(index.by_municipality.get(key, []))

    if not matches:
        return [], []

    types = {t for _, t in matches}
    ids = sorted({aid for aid, _ in matches})
    return ids[:max_assets], _sectors_for(types)
