"""Map WATERS API responses to aguayluz entities.

Strict separation:
  - I/O lives in `client.py` and `endpoints.py`.
  - This module is pure: response dict in, validated entity out.

Conventions per AGUAYLUZ_PR_SKILL.md:
  - All WATERS-sourced records are evidence_tier T1 (primary EPA data).
  - VPU 21 records (Puerto Rico) carry `attribute_coverage="partial"` because
    the EPA NHDPlus V2.1 dataset inventory lists Vogel/VPUAttribute/NLCD
    extensions as NOT AVAILABLE for VPU 21. Federation spec rule 8 forbids
    silent substitution, so we surface the gap rather than hide it.
  - Points outside the Puerto Rico bbox (lat [17.7, 18.7], lon [-67.95, -65.2])
    route to a `ReviewQueueItem` instead of constructing a `UtilityAsset` —
    the JSON Schema would reject them anyway, but the review queue carries
    the human-readable reason.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal
from urllib.parse import urlencode

from ..confidence import score as confidence_score
from ..models import AssetType, GeometryType, ReviewStatus, ServiceEvent, UtilityAsset
from .endpoints import first_flowline

# PR bbox — keep in sync with utility_asset.schema.json and the plan.
PR_LAT_MIN, PR_LAT_MAX = 17.7, 18.7
PR_LON_MIN, PR_LON_MAX = -67.95, -65.2

WATERS_BASE = "https://api.epa.gov/waters"


class ReviewQueueItem(dict):
    """Dict subclass so it round-trips through json validation cleanly.

    Fields match `schemas/review_queue.schema.json` per-item shape.
    """


def _source_ref(path: str, params: dict[str, Any]) -> tuple[str, str]:
    """Return (canonical_url, sha256_of_canonical_url)."""
    qs = urlencode(sorted(params.items()))
    url = f"{WATERS_BASE}{path}?{qs}"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return url, digest


def _in_pr_bbox(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return True  # null coords are allowed; only out-of-range fails
    return PR_LAT_MIN <= lat <= PR_LAT_MAX and PR_LON_MIN <= lon <= PR_LON_MAX


def _attribute_coverage_for(vpuid: str | None) -> Literal["full", "partial"]:
    return "partial" if vpuid == "21" else "full"


def _coords_from_flowline(flowline: dict[str, Any]) -> tuple[float | None, float | None]:
    """First coordinate of the flowline shape if present; otherwise None/None."""
    shape = flowline.get("shape") or {}
    coords = shape.get("coordinates")
    if not coords:
        return None, None
    # GeoJSON LineString-ish — coords[0] is a [lon, lat] pair
    try:
        lon, lat = coords[0][0], coords[0][1]
        return float(lat), float(lon)
    except (IndexError, TypeError, ValueError):
        return None, None


def point_to_utility_asset(
    point_idx_resp: dict[str, Any],
    *,
    asset_id: str,
    asset_name: str,
    asset_type: AssetType,
    asset_subtype: str,
    municipality: str,
    operator: str | None = None,
    snap_lat: float | None = None,
    snap_lon: float | None = None,
    geometry_type: GeometryType = "point",
    review_status: ReviewStatus = "accepted",
) -> UtilityAsset | ReviewQueueItem:
    """Convert a `/v1/pointindexing` response into a `UtilityAsset` (or review item).

    `snap_lat`/`snap_lon` are the input coords used to make the call — we keep
    them on the asset so the record is reproducible. If the input coords are
    out of the PR bbox we return a ReviewQueueItem; this catches caller errors
    early instead of letting schema validation reject the asset later.
    """
    flowline = first_flowline(point_idx_resp)
    if flowline is None:
        return ReviewQueueItem(
            record_ref=asset_id,
            reason="WATERS pointindexing returned no flowlines (no snap match)",
            severity="warn",
            evidence_tier="T1",
            confidence=0,
            notes=None,
        )

    if not _in_pr_bbox(snap_lat, snap_lon):
        return ReviewQueueItem(
            record_ref=asset_id,
            reason=f"input snap coords ({snap_lat}, {snap_lon}) outside PR bbox",
            severity="warn",
            evidence_tier="T1",
            confidence=0,
            notes=None,
        )

    vpuid = flowline.get("nhdplus_region")
    coverage = _attribute_coverage_for(vpuid)

    params: dict[str, Any] = {"output": "JSON"}
    if snap_lon is not None and snap_lat is not None:
        params["pgeometry"] = f"POINT({snap_lon} {snap_lat})"
    source_ref, source_hash = _source_ref("/v1/pointindexing", params)

    confidence = confidence_score(
        tier="T1",
        source_count=1,
        has_coords=snap_lat is not None and snap_lon is not None,
        attribute_coverage=coverage,
    )

    return UtilityAsset(
        asset_id=asset_id,
        asset_name=asset_name,
        asset_type=asset_type,
        asset_subtype=asset_subtype,
        operator=operator,
        municipality=municipality,
        lat=snap_lat,
        lon=snap_lon,
        geometry_type=geometry_type,
        status="active",
        source_ref=source_ref,
        source_hash=source_hash,
        evidence_tier="T1",
        confidence=confidence,
        review_status=review_status,
        attribute_coverage=coverage,
        vpuid=vpuid,
        comid=int(flowline["comid"]) if flowline.get("comid") is not None else None,
        reachcode=flowline.get("reachcode"),
        measure=float(flowline["fmeasure"]) if flowline.get("fmeasure") is not None else None,
    )


def service_event_from_owld(
    owld_resp: dict[str, Any],
    *,
    event_id: str,
    affected_area: str,
    event_type: str = "service_interruption",
    snap_lat: float | None = None,
    snap_lon: float | None = None,
    linked_asset_ids: list[str] | None = None,
    review_status: ReviewStatus = "needs_review",
) -> ServiceEvent | ReviewQueueItem:
    """Map an `/v1/owldlocator` response (downstream waterbodies) to a ServiceEvent.

    OWLD returns the *downstream cascade* of waterbodies from a release point —
    useful for surfacing which named waterbodies would be affected by a service
    interruption. We summarize names into `affected_area` rather than
    enumerating each waterbody, keeping the record federation-bound.
    """
    if not _in_pr_bbox(snap_lat, snap_lon):
        return ReviewQueueItem(
            record_ref=event_id,
            reason=f"input snap coords ({snap_lat}, {snap_lon}) outside PR bbox",
            severity="warn",
            evidence_tier="T1",
            confidence=0,
            notes=None,
        )

    output = owld_resp.get("output", {}) if isinstance(owld_resp, dict) else {}
    waterbodies = output.get("waterbodies", []) if isinstance(output, dict) else []
    affected_count = len(waterbodies) if isinstance(waterbodies, list) else 0

    params: dict[str, Any] = {"output": "JSON"}
    if snap_lon is not None and snap_lat is not None:
        params["pgeometry"] = f"POINT({snap_lon} {snap_lat})"
    source_ref, source_hash = _source_ref("/v1/owldlocator", params)

    # OWLD data is upstream EPA but secondary for service-event purposes:
    # tier T2 (operational/institutional) rather than T1 (technical/primary).
    confidence = confidence_score(
        tier="T2",
        source_count=1,
        has_coords=snap_lat is not None and snap_lon is not None,
        attribute_coverage="full",
    )

    return ServiceEvent(
        event_id=event_id,
        event_type=event_type,  # validated by the Literal in models.py
        affected_area=affected_area,
        start_time=None,
        end_time=None,
        reported_customers_or_users=affected_count if affected_count else None,
        source_ref=source_ref,
        source_hash=source_hash,
        evidence_tier="T2",
        confidence=confidence,
        review_status=review_status,
        linked_asset_ids=linked_asset_ids or [],
    )
