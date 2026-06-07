"""Watershed (upstream drainage area) delineation per utility asset.

For each `water`/`wastewater` asset with a valid snap (`lat`+`lon`), call
the WATERS `/v3/drainageareadelineation` endpoint, extract the area + bounds
+ NHDPlusID + headwater COMIDs, and emit a `WatershedDelineation` record.

Geometry (the upstream polygon) is persisted to a sidecar GeoJSON under
`outputs/geometry/` rather than embedded in the entity — keeps the JSON
Schema gate fast and the Base44 envelope small.

VPU 21 (PR) records carry `attribute_coverage="partial"` because flow-volume
attributes (Vogel/VPUAttribute/NLCD) used to scale the watershed-yield
calculations are unavailable for VPU 21 per the EPA inventory.

Demo mode injects a fixture `snap_fn`. Live mode wires
`waters.endpoints.drainage_area_delineation`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from ..confidence import score as confidence_score
from ..models import EvidenceTier

DEL_SOURCE_URL = "https://api.epa.gov/waters/v3/drainageareadelineation"

DelineationSnapFn = Callable[[float, float], dict[str, Any]]


@dataclass(frozen=True)
class DelineationReviewItem:
    """Lightweight record routed to the review queue when delineation fails."""

    record_ref: str
    reason: str
    severity: str = "warn"
    confidence: int = 0


def _source_ref(asset_id: str, lon: float | None, lat: float | None) -> tuple[str, str]:
    params: dict[str, Any] = {"output": "JSON"}
    if lon is not None and lat is not None:
        params["pgeometry"] = f"POINT({lon} {lat})"
    qs = urlencode(sorted(params.items()))
    url = f"{DEL_SOURCE_URL}?{qs}"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return url, digest


def _extract_first_feature(response: dict[str, Any]) -> dict[str, Any] | None:
    fc = response.get("Result_Delineated_Area") or {}
    features = fc.get("features") or []
    return features[0] if features else None


def _polygon_bbox(coords: list[Any]) -> list[float]:
    """Compute [lon_min, lat_min, lon_max, lat_max] from a GeoJSON polygon's rings."""
    lons: list[float] = []
    lats: list[float] = []

    def walk(item: Any) -> None:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and isinstance(item[0], (int, float))
            and isinstance(item[1], (int, float))
        ):
            lons.append(float(item[0]))
            lats.append(float(item[1]))
        elif isinstance(item, list):
            for sub in item:
                walk(sub)

    walk(coords)
    if not lons:
        return [0.0, 0.0, 0.0, 0.0]
    return [min(lons), min(lats), max(lons), max(lats)]


def _resolve_bbox(feature: dict[str, Any]) -> list[float]:
    """Prefer feature.bbox; otherwise compute from geometry."""
    bbox = feature.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        return [float(x) for x in bbox]
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates")
    if coords:
        return _polygon_bbox(coords)
    return [0.0, 0.0, 0.0, 0.0]


def delineate_assets(
    assets: list[dict[str, Any]],
    *,
    snap_fn: DelineationSnapFn,
    geometry_dir: str | None = None,
    evidence_tier: EvidenceTier = "T1",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run watershed delineation for every snap-able water/wastewater asset.

    Returns `(records, review_items)`. `snap_fn(lon, lat)` returns the raw
    `/v3/drainageareadelineation` response dict.

    `geometry_dir` (if set) is the relative path the script will persist the
    sidecar GeoJSON under; we only record the planned filename so the gate
    can validate the entity without us doing the write here.
    """
    records: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []

    for asset in assets:
        if asset.get("asset_type") not in ("water", "wastewater"):
            continue
        lat = asset.get("lat")
        lon = asset.get("lon")
        if lat is None or lon is None:
            review.append({
                "record_ref": asset["asset_id"],
                "reason": "asset missing snap coordinates",
                "severity": "warn",
                "evidence_tier": evidence_tier,
                "confidence": 0,
                "notes": None,
            })
            continue

        try:
            response = snap_fn(lon, lat)
        except Exception as exc:  # noqa: BLE001
            review.append({
                "record_ref": asset["asset_id"],
                "reason": f"delineation failed: {exc.__class__.__name__}",
                "severity": "warn",
                "evidence_tier": evidence_tier,
                "confidence": 0,
                "notes": None,
            })
            continue

        feature = _extract_first_feature(response)
        if feature is None:
            review.append({
                "record_ref": asset["asset_id"],
                "reason": "delineation returned no Result_Delineated_Area features",
                "severity": "warn",
                "evidence_tier": evidence_tier,
                "confidence": 0,
                "notes": None,
            })
            continue

        properties = feature.get("properties") or {}
        nhdplus_id_raw = properties.get("NHDPlusID")
        try:
            nhdplus_id = int(nhdplus_id_raw) if nhdplus_id_raw is not None else None
        except (TypeError, ValueError):
            nhdplus_id = None
        try:
            area_sqkm = float(properties.get("AreaSqKm") or 0.0)
        except (TypeError, ValueError):
            area_sqkm = 0.0

        # Headwater COMIDs (when WATERS includes them in properties).
        headwater_raw = properties.get("Headwater_COMIDs") or properties.get("headwater_comids") or []
        if isinstance(headwater_raw, str):
            headwater_raw = [c.strip() for c in headwater_raw.split(",") if c.strip()]
        headwater_comids: list[int] = []
        for h in headwater_raw or []:
            try:
                headwater_comids.append(int(h))
            except (TypeError, ValueError):
                continue

        bbox = _resolve_bbox(feature)
        source_ref, source_hash = _source_ref(asset["asset_id"], lon, lat)

        # Mirror M3's attribute_coverage rule — VPU 21 is partial across the board.
        attribute_coverage = "partial" if asset.get("vpuid") == "21" else "full"

        confidence = confidence_score(
            tier=evidence_tier,
            source_count=1,
            has_coords=True,
            attribute_coverage=attribute_coverage,  # type: ignore[arg-type]
        )

        geometry_sidecar = None
        if geometry_dir is not None:
            safe_id = asset["asset_id"].replace("/", "_")
            geometry_sidecar = f"{geometry_dir.rstrip('/')}/watershed_{safe_id}.geojson"

        records.append({
            "asset_id": asset["asset_id"],
            "nhdplus_id": nhdplus_id,
            "area_sqkm": round(area_sqkm, 3),
            "headwater_comids": headwater_comids,
            "bounds_bbox": bbox,
            "geometry_sidecar": geometry_sidecar,
            "source_ref": source_ref,
            "source_hash": source_hash,
            "evidence_tier": evidence_tier,
            "confidence": confidence,
            "review_status": "needs_review",
            "attribute_coverage": attribute_coverage,
        })

    return records, review
