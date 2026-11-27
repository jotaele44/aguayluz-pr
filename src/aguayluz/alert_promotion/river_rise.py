"""Promote USGS river rate-of-rise episodes into WEATHER_HAZARD AlertEvents.

An *episode* is one ``USGS_RISE:`` canonical event on the hydromet plane
(``scripts/ingest_usgs_river_rise.py``): a stream gauge whose stage rose at a RAPID or
FLASH rate (:mod:`aguayluz.hazard_adapters.river_rise`). It is an **observed** rise read
from provisional USGS data about an hour after the fact, not an NWS warning, so on its
own it never reaches the critical push/SMS floor:

================================  ========
RAPID_RISE                        2
FLASH_RISE                        3
… corroborated                    +1 (at most 4 — critical → Hub push/SMS)
================================  ========

Corroboration is independent evidence that the rise is a flood, over the episode's span
(from two hours before onset to its end, or to the latest reading while it is open):

* an NWS **Flash Flood Warning** naming the gauge's municipio
  (``data/service_events.jsonl``, written by ``ingest_nws_alerts.py``);
* an **NWPS flood episode** at minor stage or higher on the NWPS gauge bound to the same
  USGS site (``_nwpsflood_``), i.e. NWS's own published thresholds were crossed;
* the episode's **projected minor-stage crossing** within 60 minutes, recorded only when
  the NWPS gauge reads in the same datum as the USGS sensor.

Discharge is rated from the same stage sensor and never corroborates. Uncorroborated
alerts are ``needs_review``. An alert is only ``accepted`` when corroborated, bound to a
municipio and not stale.

No alert is raised until the thresholds config says calibration passed
(``promotion.enabled``); ``scripts/build_alerts.py`` reads that flag into
:class:`~aguayluz.alert_promotion.hydromet.HydrometInputs`.

Pure functions: no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from ..alerts import AlertEvent
from ..hazard_adapters import nwps_gauges, river_rise
from ..hazard_plane import HazardRecord, RecordStatus
from ..hydromet.store import revision_chains
from ..impact import AssetIndex, in_alert_bounds, link_impact, merge_asset_ids
from ..water_alerts import _geo_key
from .hydromet import NWPS_FLOOD_MARKER, HydrometInputs, flood_episodes

RIVER_RISE_MARKER = "_riverrise_"

#: Base severity by the episode's peak class; corroboration adds one, capped at 4.
RISE_SEVERITY: dict[str, int] = {"RAPID_RISE": 2, "FLASH_RISE": 3}
CORROBORATED_MAX_SEVERITY = 4

#: A closed episode keeps being reported (status ``closed``) for this long.
CLOSED_RETENTION = timedelta(days=30)

#: Corroborating evidence may start this long before the episode's onset.
CORROBORATION_LEAD = timedelta(hours=2)

#: NWPS categories that count as flooding (action stage is "prepare", not flood).
NWPS_FLOOD_CORROBORATES = ("minor", "moderate", "major")

_EVENT_RE = re.compile(r"event='([^']*)'")
_PR_SUFFIX = re.compile(r",\s*PR\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Corroboration:
    """One piece of independent evidence that a rise is a flood."""

    kind: Literal["nws_flash_flood_warning", "nwps_flood_category", "minor_stage_projection"]
    ref: str
    detail: str


@dataclass(frozen=True)
class FlashFloodWindow:
    event_id: str
    start: datetime
    end: datetime
    municipio_keys: frozenset[str]
    municipios: tuple[str, ...]


def _parse(value: Any) -> datetime | None:
    return river_rise.parse_time(value) if isinstance(value, str) else None


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def flash_flood_windows(events: list[dict[str, Any]]) -> list[FlashFloodWindow]:
    """NWS Flash Flood Warnings in the service events, with their warned municipios.

    ``affected_area`` reads ``"Mayaguez, PR; Moca, PR"``; the ``, PR`` suffix is stripped
    before matching. A warning with no end time is taken to last three hours.
    """
    out: list[FlashFloodWindow] = []
    for event in events:
        match = _EVENT_RE.search(str(event.get("status_text") or ""))
        if not match or match.group(1).strip().lower() != "flash flood warning":
            continue
        start = _parse(event.get("start_time"))
        if start is None:
            continue
        end = _parse(event.get("end_time")) or start + timedelta(hours=3)
        names = tuple(_PR_SUFFIX.sub("", part).strip()
                      for part in str(event.get("affected_area") or "").split(";") if part.strip())
        out.append(FlashFloodWindow(str(event.get("event_id") or ""), start, max(end, start),
                                    frozenset(_geo_key(n) for n in names), names))
    return out


def _nwps_alert_id(lid: str, start: datetime) -> str:
    return f"AYL_ALR_{start:%Y%m%d}{NWPS_FLOOD_MARKER}{lid.lower()}_{start:%H%M}"


def corroborate(
    span: tuple[datetime, datetime],
    municipio: str | None,
    chain: list[HazardRecord],
    windows: list[FlashFloodWindow],
    nwps_episodes: list[tuple[str, Any]],
) -> list[Corroboration]:
    """Independent evidence overlapping ``span`` (onset − 2 h → end or latest reading)."""
    lo, hi = span[0] - CORROBORATION_LEAD, span[1]
    found: list[Corroboration] = []
    key = _geo_key(municipio) if municipio else None
    for window in windows:
        if key and key in window.municipio_keys and window.start <= hi and window.end >= lo:
            found.append(Corroboration(
                "nws_flash_flood_warning", window.event_id,
                f"NWS Flash Flood Warning for {', '.join(window.municipios)}, "
                f"{_utc(window.start)} → {_utc(window.end)}"))
    for lid, episode in nwps_episodes:
        end = episode.end or hi
        if episode.peak_category in NWPS_FLOOD_CORROBORATES and episode.start <= hi and end >= lo:
            found.append(Corroboration(
                "nwps_flood_category", _nwps_alert_id(lid, episode.start),
                f"NWPS gauge {lid} at {episode.peak_category} flood stage from {_utc(episode.start)}"))
    flagged = next((r for r in chain if r.normalized_values.get("minor_within_60m")), None)
    if flagged is not None:
        minutes = ((flagged.normalized_values.get("projection") or {}).get("to_minor_minutes"))
        found.append(Corroboration(
            "minor_stage_projection", flagged.record_id,
            f"projected to reach NWPS minor stage in {minutes:g} min at the observed rate "
            "(same datum as the NWPS gauge)" if isinstance(minutes, (int, float))
            else "projected to reach NWPS minor stage within 60 min"))
    return found


def _municipalities(row: dict[str, Any], record: HazardRecord) -> tuple[list[str], bool]:
    if row.get("municipio"):
        return [str(row["municipio"])], True
    if row.get("candidate_municipio"):
        return [str(row["candidate_municipio"])], False
    return ["(unscoped)"], False


def river_rise_alert(
    chain: list[HazardRecord],
    row: dict[str, Any],
    corroborations: list[Corroboration],
    index: AssetIndex,
    now: datetime | None,
) -> AlertEvent:
    """One alert for one rise episode (its revision chain, oldest first)."""
    head = chain[-1]
    values = head.normalized_values
    site = head.source_record_id
    onset = head.observed_from or head.effective_from
    if onset is None:
        raise ValueError(f"{head.canonical_event_id}: rise episode without an onset")
    closed = head.status == RecordStatus.TERMINATED
    end = head.effective_to if closed else None
    peak = str(values.get("peak_class") or "RAPID_RISE")
    base = RISE_SEVERITY.get(peak, 2)
    severity = min(base + 1, CORROBORATED_MAX_SEVERITY) if corroborations else base

    name = str(row.get("name") or head.title_raw or f"USGS {site}")
    municipalities, resolved = _municipalities(row, head)
    lat = row.get("latitude", (head.raw_attributes or {}).get("latitude"))
    lon = row.get("longitude", (head.raw_attributes or {}).get("longitude"))
    exact = in_alert_bounds(lat, lon)
    linked, sectors = link_impact(None, None, [m for m in municipalities if m != "(unscoped)"],
                                  index, radius_km=None)
    asset_id = head.facility_id or row.get("asset_id")

    stale = False
    if not closed:
        stale = row.get("data_state") in {river_rise.STALE, river_rise.NO_STAGE, None}
        latest = _parse((row.get("latest") or {}).get("time"))
        if now is not None and latest is not None:
            stale = stale or now - latest > timedelta(hours=3)
    review: Literal["accepted", "needs_review"] = (
        "accepted" if corroborations and resolved and not stale else "needs_review"
    )

    metrics = values.get("metrics") or {}
    peak_text = peak.replace("_", " ").lower()
    span = f"{_utc(onset)} → {_utc(end)}" if end else f"since {_utc(onset)}"
    notes = [
        f"USGS {site} stage {peak_text} ({span}); at the last revision: "
        f"Δ15m {metrics.get('rise_15m_ft')} ft, Δ1h {metrics.get('rise_1h_ft')} ft, "
        f"Δ3h {metrics.get('rise_3h_ft')} ft, rate {metrics.get('rate_ft_per_h')} ft/h.",
        "Observed rise from provisional USGS instantaneous values, about an hour behind real "
        "time (GOES relay); not an NWS warning.",
    ]
    if corroborations:
        notes.append("Corroborated: " + "; ".join(c.detail for c in corroborations) + ".")
    else:
        notes.append("Not corroborated by an NWS flash-flood warning, an NWPS flood category or "
                     "a minor-stage projection; routed to review.")
    if values.get("closed_reason"):
        notes.append(f"Closed: {values['closed_reason']}.")
    if row.get("site_note"):
        notes.append(f"Site note: {row['site_note']}")
    if stale:
        notes.append("Latest reading is stale or missing; the episode is held open for review.")
    notes.append(f"Municipio binding: {row.get('binding_evidence') or 'UNRESOLVED'}.")

    return AlertEvent(
        alert_id=f"AYL_ALR_{onset:%Y%m%d}{RIVER_RISE_MARKER}{site}_{onset:%H%M}",
        module_id="WEATHER_HAZARD",
        event_type="hazard",
        status="closed" if closed else "active",
        source_title=f"{name} — {peak_text} (river stage)",
        source_ref=f"USGS {site} {name}; https://waterdata.usgs.gov/monitoring-location/USGS-{site}/",
        source_hash=None,
        published_at=None,
        start_at=_utc(onset),
        end_at=_utc(end) if end else None,
        asset_name=name,
        asset_id=asset_id,
        operator="USGS",
        municipalities=municipalities,
        sectors_impacted=sectors,
        latitude=round(float(lat), 6) if exact else None,
        longitude=round(float(lon), 6) if exact else None,
        coord_confidence="exact" if exact else "unknown",
        severity=severity,
        confidence=75 if corroborations else 60,
        ilap_score=None,
        covert_flags=["watershed_effect"],
        gap_status="none" if corroborations else "minor",
        review_status=review,
        evidence_tier="T2",
        linked_asset_ids=merge_asset_ids([asset_id] if asset_id else [], linked),
        validation_notes=" ".join(notes),
    )


def river_rise_alerts(
    inputs: HydrometInputs | None,
    events: list[dict[str, Any]] | None = None,
    geo: dict[str, dict[str, Any]] | None = None,
    index: AssetIndex | None = None,
) -> list[AlertEvent]:
    """One alert per rise episode (open, or closed within CLOSED_RETENTION).

    Nothing is raised while ``inputs.river_rise_promotion`` is False (calibration has not
    passed).
    """
    del geo  # site coordinates come from the asset; no centroid fallback
    if inputs is None or not inputs.river_rise_promotion:
        return []
    index = index or AssetIndex()
    rows = {str(r.get("site_no")): r for r in inputs.river_rise_state if r.get("site_no")}
    windows = flash_flood_windows(events or [])
    lid_by_site = {str(r["usgs_id"]): str(r["lid"]) for r in inputs.gauge_state
                   if r.get("usgs_id") and r.get("lid")}
    nwps_by_lid: dict[str, list[Any]] = {}
    for chain in revision_chains(inputs.records, nwps_gauges.CANONICAL_PREFIX).values():
        if chain:
            nwps_by_lid[chain[0].source_record_id] = flood_episodes(chain)
    out: list[AlertEvent] = []
    for chain in revision_chains(inputs.records, river_rise.CANONICAL_PREFIX).values():
        if not chain:
            continue
        head = chain[-1]
        site = head.source_record_id
        if head.normalized_values.get("peak_class") not in RISE_SEVERITY:
            continue
        closed = head.status == RecordStatus.TERMINATED
        if closed and head.effective_to is not None and inputs.now is not None \
                and inputs.now - head.effective_to > CLOSED_RETENTION:
            continue
        row = rows.get(site) or {}
        onset = head.observed_from or head.effective_from
        if onset is None:
            continue
        latest = _parse((row.get("latest") or {}).get("time")) or head.observed_to or onset
        span_end = head.effective_to if closed and head.effective_to else max(latest, onset)
        lid = lid_by_site.get(site)
        nwps = [(lid, e) for e in nwps_by_lid.get(lid, [])] if lid else []
        municipio = row.get("municipio")
        corroborations = corroborate((onset, span_end), municipio, chain, windows, nwps)
        out.append(river_rise_alert(chain, row, corroborations, index, inputs.now))
    return sorted(out, key=lambda a: a.alert_id)


__all__ = [
    "CLOSED_RETENTION",
    "CORROBORATED_MAX_SEVERITY",
    "CORROBORATION_LEAD",
    "Corroboration",
    "FlashFloodWindow",
    "NWPS_FLOOD_CORROBORATES",
    "RISE_SEVERITY",
    "RIVER_RISE_MARKER",
    "corroborate",
    "flash_flood_windows",
    "river_rise_alert",
    "river_rise_alerts",
]
