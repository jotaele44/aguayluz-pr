"""Generate operational AlertEvents from real, already-ingested water data.

The multi-sector alert framework (:mod:`aguayluz.alerts`) ships ten modules, five
active, but ``data/alert_events.jsonl`` historically held only hand-authored seed
placeholders. This module closes that gap by projecting the producer's *real* water
signals into the alert layer:

* **CONTAMINATION** — EPA SDWIS boil-water advisories and health-based
  water-quality violations (``data/service_events.jsonl``, evidence tier T1).
* **HYDRO_OPS** — USGS daily reservoir readings (``data/reservoir_levels.jsonl``,
  T1) flagged low by a transparent *per-site statistical proxy*.

Provenance honesty:

* SDWIS-derived alerts inherit the source event's T1 tier and confidence — real
  federal data, not fabricated.
* The reservoir proxy is deliberately stamped **T2 / needs_review** with a
  ``validation_notes`` disclaimer, because official AAA operating levels (niveles
  de observación / ajuste / control) are not public. It flags a reading only
  relative to that site's *own* recorded history — it never invents an absolute
  operating threshold.
* Non-health monitoring/reporting violations are **not** promoted to alerts; they
  remain in the service-event stream. Only acute (boil-water) and health-based
  quality events become CONTAMINATION alerts.

The functions here are pure (no I/O, no wall-clock); ``scripts/build_water_alerts.py``
is the CLI that loads data, calls :func:`build_water_alerts`, and merges the result
into ``data/alert_events.jsonl``. Every returned object is a validated
:class:`aguayluz.alerts.AlertEvent`.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from typing import Any

from .alerts import AlertEvent
from .impact import MODULE_RADIUS_KM, AssetIndex, link_impact, merge_asset_ids

# Contamination severities on the workbook's 0-5 operational floor. The
# CONTAMINATION module's default floor is 3 (see config/alert_modules.yaml); an
# acute microbial boil-water notice with a tier-1 public-notification requirement
# is the most urgent, a non-acute health-based quality violation the least.
_SEV_BOIL_WATER_ACUTE = 4
_SEV_BOIL_WATER = 3
_SEV_HEALTH_VIOLATION_ACUTE = 3
_SEV_HEALTH_VIOLATION = 2

#: Only these service-event types are promoted to CONTAMINATION alerts.
_CONTAMINATION_EVENT_TYPES = frozenset({"boil_water", "water_quality_violation"})

#: Default lower-tail percentile for the reservoir-low proxy.
RESERVOIR_LOW_PERCENTILE = 10.0
#: Minimum readings a site needs before a percentile is meaningful.
RESERVOIR_MIN_HISTORY = 12


def _geo_key(name: str) -> str:
    """unaccent + upper -> match municipio centroids regardless of diacritics."""
    folded = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return " ".join(folded.upper().split())


def load_geo(municipios: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index ``pr_municipios.json`` records by their unaccent/upper name key."""
    return {_geo_key(m["name"]): m for m in municipios if m.get("name")}


def _slug(value: str, limit: int = 40) -> str:
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    out = "".join(c.lower() if c.isalnum() else "_" for c in folded)
    return "_".join(filter(None, out.split("_")))[:limit] or "event"


def _parse_status_text(text: str | None) -> dict[str, str]:
    """SDWIS ``status_text`` is space-separated ``key=value`` tokens."""
    toks: dict[str, str] = {}
    for tok in (text or "").split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            toks[k] = v
    return toks


def _municipalities(event: dict[str, Any]) -> list[str]:
    muni = event.get("municipality")
    if muni and str(muni).strip() and str(muni).lower() not in {"unknown", "puerto rico"}:
        return [str(muni)]
    area = event.get("affected_area") or ""
    parts = [p.strip().title() for p in str(area).split(",") if p.strip()]
    return parts or ["(unscoped)"]


def _centroid(muni: str, geo: dict[str, dict[str, Any]]) -> tuple[float | None, float | None]:
    rec = geo.get(_geo_key(muni)) if muni else None
    if rec and isinstance(rec.get("lat"), (int, float)) and isinstance(rec.get("lon"), (int, float)):
        return round(float(rec["lat"]), 6), round(float(rec["lon"]), 6)
    return None, None


def _event_date(event: dict[str, Any]) -> str:
    """YYYYMMDD from the event's start_time (deterministic alert_id component)."""
    start = str(event.get("start_time") or "")
    digits = "".join(ch for ch in start[:10] if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else "00000000"


def _reading_date(reading: dict[str, Any]) -> str | None:
    """The observation date of a monitoring reading.

    The canonical `monitoring_reading` schema (and `scripts/ingest_usgs_levels.py`)
    names this field ``observed_date``; ``date`` is accepted as a fallback.
    """
    return reading.get("observed_date") or reading.get("date")


def contamination_alert(
    event: dict[str, Any],
    geo: dict[str, dict[str, Any]],
    index: AssetIndex | None = None,
) -> AlertEvent | None:
    """Project one SDWIS service event into a CONTAMINATION AlertEvent.

    Returns ``None`` for events that are not acute and not health-based — those
    stay in the service-event stream rather than becoming alerts.
    """
    index = index or AssetIndex()
    etype = event.get("event_type")
    if etype not in _CONTAMINATION_EVENT_TYPES:
        return None

    toks = _parse_status_text(event.get("status_text"))
    health_based = toks.get("health_based") == "Y"
    acute = toks.get("pn_tier") == "1"

    if etype == "boil_water":
        severity = _SEV_BOIL_WATER_ACUTE if acute else _SEV_BOIL_WATER
        title = "Boil-water advisory"
    else:  # water_quality_violation
        if not health_based:
            return None  # monitoring/reporting violation — not alert-worthy
        severity = _SEV_HEALTH_VIOLATION_ACUTE if acute else _SEV_HEALTH_VIOLATION
        title = "Health-based water-quality violation"

    munis = _municipalities(event)
    lat, lon = _centroid(munis[0], geo) if munis and munis[0] != "(unscoped)" else (None, None)

    # compliance=R means "returned to compliance" -> closed; otherwise still active.
    compliance = toks.get("compliance")
    if compliance == "R":
        status = "closed"
    elif compliance:
        status = "active"
    else:
        status = "validated"

    review_status = event.get("review_status") or "needs_review"
    area = event.get("affected_area") or (munis[0] if munis else "")
    alert_id = f"AYL_ALR_{_event_date(event)}_sdwis_{_slug(event.get('event_id') or area)}"

    # SDWIS violations name a public water system by municipality, not a point — link the
    # water/wastewater assets in that municipality.
    linked, sectors = link_impact(
        None, None, munis, index, radius_km=MODULE_RADIUS_KM["CONTAMINATION"]
    )

    return AlertEvent(
        alert_id=alert_id,
        module_id="CONTAMINATION",
        event_type="quality",
        status=status,
        source_title=f"{title} @ {area}".strip(),
        source_ref=event.get("source_ref") or "EPA SDWIS",
        source_hash=event.get("source_hash"),
        published_at=None,
        start_at=event.get("start_time"),
        end_at=event.get("end_time"),
        asset_name=area or (munis[0] if munis else "PR public water system"),
        asset_id=None,
        operator=None,
        municipalities=munis,
        sectors_impacted=sectors,
        latitude=lat,
        longitude=lon,
        coord_confidence="approximate" if lat is not None else "unknown",
        severity=severity,
        confidence=int(event.get("confidence") or 80),
        ilap_score=None,
        covert_flags=[],
        gap_status="none",
        review_status=review_status,
        evidence_tier=event.get("evidence_tier") or "T1",
        linked_asset_ids=merge_asset_ids(event.get("linked_asset_ids"), linked),
        validation_notes="Derived from EPA SDWIS violation record; health-based/acute filter applied.",
    )


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolated percentile over an already-sorted list."""
    if not sorted_vals:
        raise ValueError("empty")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(rank)
    frac = rank - lo
    if lo + 1 >= len(sorted_vals):
        return sorted_vals[-1]
    return sorted_vals[lo] + frac * (sorted_vals[lo + 1] - sorted_vals[lo])


# Reservoir metrics where a LOW value is the concerning direction.
_RESERVOIR_LOW_METRICS = ("reservoir_storage_pct", "reservoir_elevation")


def reservoir_alerts(
    readings: list[dict[str, Any]],
    geo: dict[str, dict[str, Any]],
    index: AssetIndex | None = None,
    percentile: float = RESERVOIR_LOW_PERCENTILE,
    min_history: int = RESERVOIR_MIN_HISTORY,
) -> list[AlertEvent]:
    """Flag the most-recent reading per (site, metric) that sits in the site's own
    historical lower tail as a HYDRO_OPS reservoir-low alert.

    This is a *statistical* proxy (T2/needs_review), not an official AAA operating
    level. A site with fewer than ``min_history`` readings for a metric is skipped
    (percentile not yet meaningful). Only storage-percent and reservoir-elevation
    metrics are considered — the ones where a low value signals drawdown.
    """
    index = index or AssetIndex()
    # Group values by (asset_id, metric), keeping the newest reading per group.
    by_key: dict[tuple[str, str], list[float]] = {}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for r in readings:
        metric = r.get("metric")
        if metric not in _RESERVOIR_LOW_METRICS:
            continue
        try:
            val = float(r.get("value"))
        except (TypeError, ValueError):
            continue
        key = (str(r.get("asset_id")), str(metric))
        by_key.setdefault(key, []).append(val)
        prev = latest.get(key)
        if prev is None or str(_reading_date(r) or "") >= str(_reading_date(prev) or ""):
            latest[key] = r

    alerts: list[AlertEvent] = []
    for key, vals in by_key.items():
        if len(vals) < min_history:
            continue
        threshold = _percentile(sorted(vals), percentile)
        cur = latest[key]
        try:
            cur_val = float(cur.get("value"))
        except (TypeError, ValueError):
            continue
        if cur_val > threshold:
            continue  # not in the lower tail

        asset_id, metric = key
        muni = cur.get("municipality") or ""
        munis = [muni] if muni and str(muni).lower() not in {"unknown", ""} else ["(unscoped)"]
        lat, lon = _centroid(munis[0], geo) if munis[0] != "(unscoped)" else (
            cur.get("lat"), cur.get("lon"),
        )
        observed = _reading_date(cur)
        date = "".join(ch for ch in str(observed or "")[:10] if ch.isdigit())[:8] or "00000000"
        name = cur.get("asset_name") or asset_id

        # The flagged reservoir is itself a water asset; also link any co-located
        # water/wastewater/power assets in the same municipality. Sectors always include
        # water (the reservoir), plus whatever the municipality linkage adds.
        linked_ids, sectors = link_impact(
            None, None, munis, index, radius_km=MODULE_RADIUS_KM["HYDRO_OPS"]
        )
        linked_ids = merge_asset_ids([asset_id], linked_ids)
        sectors = sorted(set(sectors) | {"water"})
        alerts.append(
            AlertEvent(
                alert_id=f"AYL_ALR_{date}_resvlow_{_slug(asset_id)}",
                module_id="HYDRO_OPS",
                event_type="hazard",
                status="active",
                source_title=f"Reservoir low ({metric}) at {name}",
                source_ref=cur.get("source_ref") or f"USGS NWIS {asset_id}",
                source_hash=None,
                published_at=None,
                start_at=observed,
                end_at=None,
                asset_name=str(name),
                asset_id=asset_id,
                operator=cur.get("operator"),
                municipalities=munis,
                sectors_impacted=sectors,
                latitude=lat if isinstance(lat, (int, float)) else None,
                longitude=lon if isinstance(lon, (int, float)) else None,
                coord_confidence="approximate" if isinstance(lat, (int, float)) else "unknown",
                severity=2,
                confidence=60,
                ilap_score=None,
                covert_flags=[],
                gap_status="major",
                review_status="needs_review",
                evidence_tier="T2",
                linked_asset_ids=linked_ids,
                validation_notes=(
                    f"Statistical proxy: latest {metric}={cur_val} at or below this site's "
                    f"{percentile:g}th-percentile of {len(vals)} readings ({threshold:.3f}). "
                    "NOT an official AAA nivel de control — promote to T1 on AAA operating-level access."
                ),
            )
        )
    return alerts


def build_water_alerts(
    events: list[dict[str, Any]],
    readings: list[dict[str, Any]] | None,
    geo: dict[str, dict[str, Any]],
    index: AssetIndex | None = None,
    reservoir_percentile: float = RESERVOIR_LOW_PERCENTILE,
) -> list[AlertEvent]:
    """Build the full set of data-driven water AlertEvents (CONTAMINATION + HYDRO_OPS).

    ``index`` links each alert to the utility assets it affects; omitting it (or passing
    an empty index) yields empty linkage, preserving the prior behaviour.
    """
    idx = index if index is not None else AssetIndex()
    alerts: list[AlertEvent] = []
    for ev in events:
        alert = contamination_alert(ev, geo, idx)
        if alert is not None:
            alerts.append(alert)
    if readings:
        alerts.extend(reservoir_alerts(readings, geo, idx, percentile=reservoir_percentile))
    return alerts
