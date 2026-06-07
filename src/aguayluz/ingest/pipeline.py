"""Generic batched ingestion pipeline.

Takes `FacilitySeed` records (lat/lon + identity) and produces
`UtilityAsset` + `ReviewQueueItem` outputs by:
  1. Calling a WATERS pointindexing snap for each seed (live or mocked).
  2. Routing failures (no coords, snap miss, out-of-bbox) to the review queue.
  3. Returning aggregate counts so callers can build coverage ledgers.

The pipeline is data-source-agnostic. Adapters in this package
(`frs.py`, future `hifld.py`, etc.) produce `FacilitySeed` instances; the
pipeline doesn't know or care which source they came from.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from ..confidence import score as confidence_score
from ..models import AssetType, GeometryType, ServiceEvent, UtilityAsset
from ..waters.mapping import ReviewQueueItem, point_to_utility_asset

logger = logging.getLogger("aguayluz.ingest")


@dataclass(frozen=True)
class FacilitySeed:
    """Normalized seed record produced by a data-source adapter."""

    seed_id: str                          # stable ID, becomes asset_id
    name: str
    municipality: str
    asset_type: AssetType                 # may be "unknown" — pipeline can override
    asset_subtype: str
    lat: float | None
    lon: float | None
    operator: str | None = None
    source_provenance: str = ""           # adapter writes this (e.g. "EPA FRS NPDES")
    is_utility: bool = True               # adapter marks non-utility records False
    geometry_type: GeometryType = "point"  # HIFLD lines/polygons keep their shape


@dataclass
class IngestResult:
    assets: list[dict[str, Any]] = field(default_factory=list)
    review_items: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    @property
    def expected(self) -> int:
        return len(self.assets) + len(self.review_items) + len(self.skipped)

    @property
    def located(self) -> int:
        return len(self.assets) + len(self.review_items)

    @property
    def coverage_pct(self) -> float:
        if self.expected == 0:
            return 0.0
        return round(100.0 * len(self.assets) / self.expected, 1)


SnapFn = Callable[[float, float], dict[str, Any]]


def ingest_seeds(
    seeds: Iterable[FacilitySeed],
    *,
    snap_fn: SnapFn,
    skip_non_utility: bool = True,
) -> IngestResult:
    """Drive a batch of `FacilitySeed` through the WATERS snap pipeline.

    `snap_fn(lon, lat)` returns a `/v1/pointindexing` response dict. Callers
    inject either a live client (e.g. `lambda lon, lat: point_indexing(client, lon=lon, lat=lat)`)
    or a deterministic fake for tests/demos.

    Non-utility seeds (`seed.is_utility=False`) are dropped to `skipped` when
    `skip_non_utility=True`. Set to False to coerce every seed into the
    asset/review pipeline regardless of classification.
    """
    result = IngestResult()
    for seed in seeds:
        if skip_non_utility and not seed.is_utility:
            result.skipped.append(
                {"record_ref": seed.seed_id, "reason": f"non-utility facility: {seed.name}"}
            )
            continue

        if seed.lat is None or seed.lon is None:
            result.review_items.append(
                {
                    "record_ref": seed.seed_id,
                    "reason": "seed missing coordinates",
                    "severity": "warn",
                    "evidence_tier": "T2",
                    "confidence": 0,
                    "notes": seed.source_provenance or None,
                }
            )
            continue

        try:
            snap = snap_fn(seed.lon, seed.lat)
        except Exception as exc:  # noqa: BLE001 — adapter/snap callable may raise broadly
            logger.warning("snap failed for seed %s: %s", seed.seed_id, exc)
            result.review_items.append(
                {
                    "record_ref": seed.seed_id,
                    "reason": f"WATERS snap raised: {exc.__class__.__name__}",
                    "severity": "warn",
                    "evidence_tier": "T2",
                    "confidence": 0,
                    "notes": seed.source_provenance or None,
                }
            )
            continue

        asset_or_review = point_to_utility_asset(
            snap,
            asset_id=seed.seed_id,
            asset_name=seed.name,
            asset_type=seed.asset_type,
            asset_subtype=seed.asset_subtype,
            municipality=seed.municipality,
            operator=seed.operator,
            snap_lat=seed.lat,
            snap_lon=seed.lon,
            geometry_type=seed.geometry_type,
        )

        if isinstance(asset_or_review, ReviewQueueItem):
            item = dict(asset_or_review)
            if seed.source_provenance:
                item["notes"] = seed.source_provenance
            result.review_items.append(item)
        elif isinstance(asset_or_review, UtilityAsset):
            result.assets.append(asset_or_review.model_dump())
        # else: defensive — shouldn't happen given mapping's return type
    return result


# ---------------------------------------------------------------------------
# Event ingestion — no WATERS snap required (events are area-bound, not
# point-bound).
# ---------------------------------------------------------------------------


@dataclass
class EventIngestResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    review_items: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    @property
    def expected(self) -> int:
        return len(self.events) + len(self.review_items) + len(self.skipped)

    @property
    def coverage_pct(self) -> float:
        if self.expected == 0:
            return 0.0
        return round(100.0 * len(self.events) / self.expected, 1)


def ingest_event_seeds(
    seeds: Iterable[Any],   # accepts EventSeed-like objects (duck-typed)
    *,
    linked_asset_ids_by_seed: dict[str, list[str]] | None = None,
    skip_non_utility: bool = True,
    evidence_tier: str = "T2",
) -> EventIngestResult:
    """Map event seeds (e.g. FEMA records) into `ServiceEvent` dicts.

    Non-utility seeds (`is_utility=False`) are dropped to `skipped` when
    `skip_non_utility=True`. `linked_asset_ids_by_seed` lets callers wire
    event → asset links built upstream (M7 dependency graph will populate this).
    """
    links_map = linked_asset_ids_by_seed or {}
    result = EventIngestResult()
    for seed in seeds:
        if skip_non_utility and not getattr(seed, "is_utility", True):
            result.skipped.append(
                {"record_ref": seed.seed_id, "reason": f"non-utility event: {seed.event_type}"}
            )
            continue

        confidence = confidence_score(
            tier=evidence_tier,           # type: ignore[arg-type]
            source_count=1,
            has_coords=False,             # events are area-bound, no coords
            attribute_coverage="full",
        )

        try:
            event = ServiceEvent(
                event_id=seed.seed_id,
                event_type=seed.event_type,
                affected_area=seed.affected_area,
                start_time=seed.start_time,
                end_time=seed.end_time,
                reported_customers_or_users=seed.reported_customers_or_users,
                source_ref=seed.source_ref,
                source_hash=seed.source_hash,
                evidence_tier=evidence_tier,    # type: ignore[arg-type]
                confidence=confidence,
                review_status="needs_review",   # FEMA records are second-party — review by default
                linked_asset_ids=links_map.get(seed.seed_id, []),
                notes=getattr(seed, "notes", None),
            )
        except Exception as exc:  # noqa: BLE001 — Pydantic validation may raise on malformed seeds
            result.review_items.append(
                {
                    "record_ref": seed.seed_id,
                    "reason": f"event validation failed: {exc.__class__.__name__}",
                    "severity": "warn",
                    "evidence_tier": "T2",
                    "confidence": 0,
                    "notes": getattr(seed, "notes", None),
                }
            )
            continue

        result.events.append(event.model_dump())
    return result
