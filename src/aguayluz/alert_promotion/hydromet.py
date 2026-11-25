"""Promote NWS hydromet-plane observations into WEATHER_HAZARD AlertEvents.

River flood (NWPS)
    A *flood episode* opens on the first revision whose observed NWS flood category is
    ``action``/``minor``/``moderate``/``major`` and closes on the first later revision
    observed below action (``no_flooding``/``low_threshold``/``not_defined``). A missing
    or old observation (``obs_not_current``) neither opens nor closes an episode, so a
    gauge that goes silent mid-flood stays open — flagged ``needs_review`` — rather than
    reading as receded. Severity follows the episode's peak category:

    ======== ========
    action   2
    minor    3
    moderate 4  (critical → Hub push/SMS)
    major    5
    ======== ========

    These are NWS's own published thresholds observed at the gauge, not an issued NWS
    flood warning (warnings arrive through ``ingest_nws_alerts.py``). For a reservoir
    pool gauge (SHEF ``HP*``) the category reads as pool elevation against the dam's
    published flood stages.

Heavy rain (Stage IV)
    One alert per municipio and 12Z-12Z day whose Stage IV 1-day rainfall, summarised
    over the HRAP cells assigned to the municipio, reaches either threshold:

    ===================================== ========
    municipio mean ≥ HEAVY_RAIN_MEAN_IN   2
    any cell ≥ HEAVY_RAIN_CELL_MAX_IN     3
    ===================================== ========

    Stage IV is a post-event analysis (radar + gauges, provisional), published after the
    day closes, so these alerts stay below the critical push/SMS floor: they prompt
    turbidity, reservoir-inflow and landslide follow-up, not warning. Each stays
    ``active`` for HEAVY_RAIN_FOLLOW_UP after the window ends, then ``closed``. A
    municipio summarised over cells its polygon only touches (too small to hold a cell
    centre) is routed to review.

Pure functions: no I/O. ``now`` is passed in by ``scripts/build_alerts.py`` and only
decides staleness notes and which closed episodes are still reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from ..alerts import AlertEvent
from ..hazard_adapters import stage_iv_qpe
from ..hazard_adapters.nwps_gauges import (
    CANONICAL_PREFIX,
    FLOOD_CATEGORIES,
    NON_FLOOD_CATEGORIES,
    parse_time,
)
from ..hazard_adapters.stage_iv_qpe import (
    HEAVY_RAIN_CELL_MAX_IN,
    HEAVY_RAIN_MEAN_IN,
    heavy_rain_severity,
)
from ..hazard_plane import HazardRecord
from ..hydromet.store import current_by_event, revision_chains
from ..impact import AssetIndex, in_alert_bounds, link_impact, merge_asset_ids
from ..water_alerts import _centroid, _slug

NWPS_FLOOD_MARKER = "_nwpsflood_"

#: Operational severity (0-5) by the episode's peak NWS flood category.
FLOOD_SEVERITY: dict[str, int] = {"action": 2, "minor": 3, "moderate": 4, "major": 5}

#: A closed episode keeps being reported (status ``closed``) for this long.
CLOSED_RETENTION = timedelta(days=30)

#: An open episode whose latest observation is older than this is flagged for review.
STALE_OBSERVATION = timedelta(hours=6)

HEAVY_RAIN_MARKER = "_qpeheavy_"

#: A heavy-rain alert stays active this long after its 12Z window ends.
HEAVY_RAIN_FOLLOW_UP = timedelta(hours=72)


@dataclass(frozen=True)
class HydrometInputs:
    """What the hydromet promoters read (loaded by ``scripts/build_alerts.py``)."""

    records: list[HazardRecord] = field(default_factory=list)
    gauge_state: list[dict[str, Any]] = field(default_factory=list)
    now: datetime | None = None


@dataclass(frozen=True)
class FloodEpisode:
    lid: str
    start: datetime
    end: datetime | None
    peak_category: str
    revision_ids: tuple[str, ...]


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _category(record: HazardRecord) -> str:
    return str(record.normalized_values.get("flood_category") or "")


def _when(record: HazardRecord) -> datetime | None:
    return record.observed_from or parse_time(record.normalized_values.get("valid_time"))


def flood_episodes(chain: list[HazardRecord]) -> list[FloodEpisode]:
    """Flood episodes in one gauge's revision chain (oldest first)."""
    episodes: list[FloodEpisode] = []
    start: datetime | None = None
    peak = ""
    ids: list[str] = []
    lid = chain[0].source_record_id if chain else ""
    for record in chain:
        category, when = _category(record), _when(record)
        if category in FLOOD_CATEGORIES:
            if start is None:
                if when is None:
                    continue
                start, peak, ids = when, category, []
            elif FLOOD_CATEGORIES.index(category) > FLOOD_CATEGORIES.index(peak):
                peak = category
            ids.append(record.record_id)
        elif category in NON_FLOOD_CATEGORIES and start is not None:
            ids.append(record.record_id)
            episodes.append(FloodEpisode(lid, start, when or start, peak, tuple(ids)))
            start, peak, ids = None, "", []
    if start is not None:
        episodes.append(FloodEpisode(lid, start, None, peak, tuple(ids)))
    return episodes


def _municipalities(state: dict[str, Any]) -> tuple[list[str], bool]:
    """Alert municipios and whether the binding is resolved.

    A gauge on a boundary river whose polygon and NWPS county disagree stays UNRESOLVED
    in the plane; its alert names both candidates (the flood reaches both banks) and is
    routed to review instead of guessing one.
    """
    if state.get("municipio"):
        return [str(state["municipio"])], True
    names = [n for n in (state.get("county_raw"), state.get("candidate_municipio")) if n]
    unique = list(dict.fromkeys(str(n) for n in names))
    return (unique or ["(unscoped)"]), False


def river_flood_alert(
    episode: FloodEpisode,
    state: dict[str, Any],
    index: AssetIndex,
    now: datetime | None,
) -> AlertEvent:
    lid = episode.lid
    name = str(state.get("name") or lid)
    municipalities, resolved = _municipalities(state)
    lat, lon = state.get("latitude"), state.get("longitude")
    exact = in_alert_bounds(lat, lon)
    a_lat = round(float(lat), 6) if exact and lat is not None else None
    a_lon = round(float(lon), 6) if exact and lon is not None else None
    linked, sectors = link_impact(None, None, municipalities, index, radius_km=None)
    asset_id = state.get("asset_id")
    pool = str(state.get("pedts_observed") or "").upper().startswith("HP")
    thresholds = state.get("thresholds") or {}
    peak_stage = (thresholds.get(episode.peak_category) or {}).get("stage")
    unit = state.get("threshold_stage_unit") or (state.get("observed") or {}).get("stage_unit") or ""

    stale = False
    if episode.end is None and now is not None:
        observed_at = parse_time((state.get("observed") or {}).get("valid_time"))
        stale = observed_at is None or now - observed_at > STALE_OBSERVATION
    review: Literal["accepted", "needs_review"] = (
        "accepted" if resolved and not stale else "needs_review"
    )
    what = "reservoir pool" if pool else "river stage"
    threshold_text = f" (≥ {peak_stage:g} {unit})" if isinstance(peak_stage, (int, float)) else ""
    span = f"{_utc(episode.start)} → {_utc(episode.end)}" if episode.end else f"since {_utc(episode.start)}"
    notes = [
        f"NWS flood category '{episode.peak_category}'{threshold_text} observed at NWPS gauge "
        f"{lid}{' (USGS ' + str(state['usgs_id']) + ')' if state.get('usgs_id') else ''}, "
        f"{what}, {span}.",
        "Observed against NWS-published thresholds; not an issued NWS warning "
        "(warnings arrive via ingest_nws_alerts.py).",
        f"Municipio binding: {state.get('binding_evidence') or 'UNRESOLVED'}.",
    ]
    if stale:
        notes.append("Latest observation is stale or missing; the episode is held open for review.")

    return AlertEvent(
        alert_id=f"AYL_ALR_{episode.start:%Y%m%d}{NWPS_FLOOD_MARKER}{lid.lower()}_{episode.start:%H%M}",
        module_id="WEATHER_HAZARD",
        event_type="hazard",
        status="active" if episode.end is None else "closed",
        source_title=f"{name} — {episode.peak_category} flood stage ({what})",
        source_ref=f"NWPS-{lid} {name}; https://water.noaa.gov/gauges/{lid.lower()}",
        source_hash=None,
        published_at=None,
        start_at=_utc(episode.start),
        end_at=_utc(episode.end) if episode.end else None,
        asset_name=name,
        asset_id=asset_id,
        operator="NOAA/NWS NWPS",
        municipalities=municipalities,
        sectors_impacted=sectors,
        latitude=a_lat,
        longitude=a_lon,
        coord_confidence="exact" if exact else "unknown",
        severity=FLOOD_SEVERITY[episode.peak_category],
        confidence=85,
        ilap_score=None,
        covert_flags=[],
        gap_status="none",
        review_status=review,
        evidence_tier="T1",
        linked_asset_ids=merge_asset_ids([asset_id] if asset_id else [], linked),
        validation_notes=" ".join(notes),
    )


def river_flood_alerts(
    inputs: HydrometInputs | None,
    geo: dict[str, dict[str, Any]] | None = None,
    index: AssetIndex | None = None,
) -> list[AlertEvent]:
    """One alert per NWPS flood episode (open, or closed within CLOSED_RETENTION)."""
    del geo  # gauge coordinates come from the source; no centroid fallback
    if inputs is None:
        return []
    index = index or AssetIndex()
    state_by_lid = {str(r.get("lid")): r for r in inputs.gauge_state if r.get("lid")}
    out: list[AlertEvent] = []
    for chain in revision_chains(inputs.records, CANONICAL_PREFIX).values():
        if not chain:
            continue
        lid = chain[0].source_record_id
        state = state_by_lid.get(lid) or {
            "lid": lid,
            "name": chain[-1].title_raw,
            "thresholds": chain[-1].normalized_values.get("thresholds") or {},
        }
        for episode in flood_episodes(chain):
            if (
                episode.end is not None
                and inputs.now is not None
                and inputs.now - episode.end > CLOSED_RETENTION
            ):
                continue
            out.append(river_flood_alert(episode, state, index, inputs.now))
    return out


def heavy_rain_alert(
    record: HazardRecord,
    severity: int,
    geo: dict[str, dict[str, Any]],
    index: AssetIndex,
    now: datetime | None,
) -> AlertEvent:
    values = record.normalized_values
    municipio = str(values.get("municipio") or record.normalized_label)
    if record.observed_to is None:
        raise ValueError(f"{record.record_id}: Stage IV record without a window end")
    end = record.observed_to
    start = record.observed_from or end - timedelta(days=1)
    follow_up_end = end + HEAVY_RAIN_FOLLOW_UP
    closed = now is not None and now > follow_up_end
    lat, lon = _centroid(municipio, geo)
    linked, sectors = link_impact(None, None, [municipio], index, radius_km=None)
    centres = values.get("method") == "raster_cell_centres_in_polygon"
    review: Literal["accepted", "needs_review"] = "accepted" if centres else "needs_review"
    pct = values.get("pct_of_normal")
    pct_text = f", {pct:g}% of the PRISM normal" if isinstance(pct, (int, float)) else ""
    url = record.raw_attributes.get("url")
    notes = [
        f"Stage IV 1-day rainfall {start:%Y-%m-%d} 12Z → {end:%Y-%m-%d} 12Z: "
        f"municipio mean {values.get('obs_mean_in')} in over {values.get('cell_count')} HRAP "
        f"cell(s), wettest cell {values.get('obs_max_in')} in{pct_text}.",
        f"Thresholds: mean ≥ {HEAVY_RAIN_MEAN_IN:g} in → 2, any cell ≥ "
        f"{HEAVY_RAIN_CELL_MAX_IN:g} in → 3.",
        "Post-event analysis (radar + gauges, provisional), not an NWS warning; supports "
        "turbidity, reservoir-inflow and landslide follow-up.",
        f"Municipio binding: {values.get('method') or 'UNRESOLVED'}.",
    ]
    if not centres:
        notes.append("Summarised over cells the polygon only touches; routed to review.")
    return AlertEvent(
        alert_id=f"AYL_ALR_{end:%Y%m%d}{HEAVY_RAIN_MARKER}{_slug(municipio)}",
        module_id="WEATHER_HAZARD",
        event_type="hazard",
        status="closed" if closed else "active",
        source_title=f"{municipio} — heavy rain, {values.get('obs_mean_in')} in municipio mean (Stage IV 1-day)",
        source_ref=f"NWS Stage IV PR {record.source_record_id}" + (f"; {url}" if url else ""),
        source_hash=None,
        published_at=None,
        start_at=_utc(start),
        end_at=_utc(follow_up_end) if closed else None,
        asset_name=municipio,
        asset_id=None,
        operator="NOAA/NWS Stage IV",
        municipalities=[municipio],
        sectors_impacted=sectors,
        latitude=lat,
        longitude=lon,
        coord_confidence="approximate" if lat is not None else "unknown",
        severity=severity,
        confidence=75,
        ilap_score=None,
        covert_flags=[],
        gap_status="none",
        review_status=review,
        evidence_tier="T1",
        linked_asset_ids=merge_asset_ids([], linked),
        validation_notes=" ".join(notes),
    )


def heavy_rain_alerts(
    inputs: HydrometInputs | None,
    geo: dict[str, dict[str, Any]] | None = None,
    index: AssetIndex | None = None,
) -> list[AlertEvent]:
    """One alert per municipio × 1-day window at or above a heavy-rain threshold.

    Reads the current revision of each Stage IV 1-day event; closed alerts are reported
    for CLOSED_RETENTION after their follow-up period ends. Unbound zones never alert.
    """
    if inputs is None:
        return []
    geo = geo or {}
    index = index or AssetIndex()
    out: list[AlertEvent] = []
    for record in current_by_event(inputs.records, stage_iv_qpe.CANONICAL_PREFIX).values():
        values = record.normalized_values
        if values.get("window") != "1day" or not record.municipality_id or record.observed_to is None:
            continue
        severity = heavy_rain_severity(values)
        if severity is None:
            continue
        if (
            inputs.now is not None
            and inputs.now - (record.observed_to + HEAVY_RAIN_FOLLOW_UP) > CLOSED_RETENTION
        ):
            continue
        out.append(heavy_rain_alert(record, severity, geo, index, inputs.now))
    return sorted(out, key=lambda a: a.alert_id)


def hydromet_alerts(
    inputs: HydrometInputs | None,
    geo: dict[str, dict[str, Any]] | None = None,
    index: AssetIndex | None = None,
) -> list[AlertEvent]:
    """Every hydromet promoter, for the registry in :mod:`aguayluz.alert_promotion`."""
    return river_flood_alerts(inputs, geo, index) + heavy_rain_alerts(inputs, geo, index)


__all__ = [
    "CLOSED_RETENTION",
    "FLOOD_SEVERITY",
    "FloodEpisode",
    "HEAVY_RAIN_CELL_MAX_IN",
    "HEAVY_RAIN_FOLLOW_UP",
    "HEAVY_RAIN_MARKER",
    "HEAVY_RAIN_MEAN_IN",
    "HydrometInputs",
    "NWPS_FLOOD_MARKER",
    "STALE_OBSERVATION",
    "flood_episodes",
    "heavy_rain_alert",
    "heavy_rain_alerts",
    "heavy_rain_severity",
    "hydromet_alerts",
    "river_flood_alert",
    "river_flood_alerts",
]
