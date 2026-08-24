"""Promote ingested USDM drought classification and NCEI precipitation-shortfall
readings into WEATHER_HAZARD AlertEvents.

``config/alert_modules.yaml``'s WEATHER_HAZARD notes have named "drought, rainfall"
since the module was seeded, but nothing generated an alert from either signal until
``scripts/ingest_drought_usdm.py`` / ``scripts/ingest_precip_ncei.py`` existed to
ingest them.

Two independent promoters, deliberately not fused into one condition (see the ingest
scripts' docstrings): USDM already publishes an official D0-D4 severity scale, so
:func:`drought_alerts` alerts directly off the classification band — a real threshold,
not a statistical proxy, so it is stamped T1/accepted like the source data. Percent-of-
normal precipitation is a corroborating signal without an official severity scale of
its own, so :func:`precipitation_shortfall_alerts` stays T2/needs_review, matching how
:mod:`aguayluz.water_alerts`'s tail-anomaly proxies (reservoir/aquifer/coastal) are
also T2/needs_review statistical proxies rather than official operating thresholds.
Fusing the two (only alert when both agree) is a documented future enhancement once
both feeds have enough history to validate against each other.

Pure functions only (no I/O, no wall-clock) — mirrors every other promoter in this
package.
"""

from __future__ import annotations

from typing import Any

from ..alerts import AlertEvent
from ..impact import MODULE_RADIUS_KM, AssetIndex, link_impact, merge_asset_ids
from ..water_alerts import _centroid, _slug

DROUGHT_MARKER = "_drought_"
PRECIP_MARKER = "_precipshort_"

#: USDM's own official severity band, D2 (Severe Drought) or worse — not a fabricated
#: statistical threshold. D0/D1 are common in PR's wet climate and not alert-worthy on
#: their own.
DROUGHT_ALERT_FLOOR = 2

#: NOAA's commonly-cited "significantly below normal" band for percent-of-normal
#: precipitation; not tightened further here. Scoped to the 90-day window only — a
#: single dry 30-day spell is common and not itself a drought corroboration signal.
PRECIP_SHORTFALL_FLOOR = 50.0
PRECIP_SHORTFALL_WINDOW = "90d"

_DROUGHT_LABELS = {0: "D0", 1: "D1", 2: "D2", 3: "D3", 4: "D4"}


def _asset_lookup(assets: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {str(a["asset_id"]): a for a in (assets or []) if a.get("asset_id")}


def _latest_by_asset(readings: list[dict[str, Any]], metric: str, parameter_code: str | None = None) -> dict[str, dict[str, Any]]:
    """Newest reading per asset_id for one metric (optionally scoped to one parameter_code)."""
    latest: dict[str, dict[str, Any]] = {}
    for r in readings:
        if r.get("metric") != metric:
            continue
        if parameter_code is not None and r.get("parameter_code") != parameter_code:
            continue
        aid = str(r.get("asset_id") or "")
        if not aid:
            continue
        prev = latest.get(aid)
        if prev is None or str(r.get("observed_date") or "") >= str(prev.get("observed_date") or ""):
            latest[aid] = r
    return latest


def drought_alerts(
    readings: list[dict[str, Any]],
    geo: dict[str, dict[str, Any]],
    index: AssetIndex | None = None,
    assets: list[dict[str, Any]] | None = None,
) -> list[AlertEvent]:
    """Flag the newest USDM classification per municipio when it reaches D2+ (Severe)."""
    index = index or AssetIndex()
    by_asset = _asset_lookup(assets)
    latest = _latest_by_asset(readings, "drought_category")

    alerts: list[AlertEvent] = []
    for aid, r in sorted(latest.items()):
        raw_value = r.get("value")
        if raw_value is None:
            continue
        try:
            ordinal = int(float(raw_value))
        except (TypeError, ValueError):
            continue
        if ordinal < DROUGHT_ALERT_FLOOR:
            continue
        asset = by_asset.get(aid, {})
        muni = str(asset.get("municipality") or "")
        munis = [muni] if muni and muni.lower() not in {"unknown", ""} else ["(unscoped)"]
        lat, lon = asset.get("lat"), asset.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            lat, lon = _centroid(munis[0], geo) if munis[0] != "(unscoped)" else (None, None)

        observed = str(r.get("observed_date") or "")
        date = "".join(ch for ch in observed[:10] if ch.isdigit())[:8] or "00000000"
        label = str(r.get("parameter_code") or _DROUGHT_LABELS.get(ordinal, f"D{ordinal}"))
        name = asset.get("asset_name") or munis[0]

        linked_ids, sectors = link_impact(
            None, None, munis, index, radius_km=MODULE_RADIUS_KM["WEATHER_HAZARD"]
        )
        linked_ids = merge_asset_ids([aid] if aid in by_asset else None, linked_ids)
        sectors = sorted(set(sectors) | {"water"})

        alerts.append(
            AlertEvent(
                alert_id=f"AYL_ALR_{date}{DROUGHT_MARKER}{_slug(aid)}",
                module_id="WEATHER_HAZARD",
                event_type="hazard",
                status="active",
                source_title=f"{label} drought — {name}",
                source_ref=r.get("source_ref") or "USDM",
                source_hash=r.get("source_hash"),
                published_at=None,
                start_at=observed,
                end_at=None,
                asset_name=str(name),
                asset_id=aid if aid in by_asset else None,
                operator=asset.get("operator") or "NDMC/USDM",
                municipalities=munis,
                sectors_impacted=sectors,
                latitude=lat if isinstance(lat, (int, float)) else None,
                longitude=lon if isinstance(lon, (int, float)) else None,
                coord_confidence="approximate" if isinstance(lat, (int, float)) else "unknown",
                severity=min(5, ordinal),
                confidence=int(r.get("confidence") or 80),
                ilap_score=None,
                covert_flags=[],
                gap_status="none",
                review_status="accepted",
                evidence_tier=r.get("evidence_tier") or "T1",
                linked_asset_ids=linked_ids,
                validation_notes=(
                    f"USDM weekly classification: {label} (official NDMC/USDM severity "
                    "band, not a derived statistical proxy)."
                ),
            )
        )
    return alerts


def precipitation_shortfall_alerts(
    readings: list[dict[str, Any]],
    geo: dict[str, dict[str, Any]],
    index: AssetIndex | None = None,
    assets: list[dict[str, Any]] | None = None,
) -> list[AlertEvent]:
    """Flag the newest 90-day percent-of-normal precipitation per station when it falls
    below :data:`PRECIP_SHORTFALL_FLOOR`. A corroborating signal, not an official
    classification — stamped T2/needs_review like the other statistical proxies."""
    index = index or AssetIndex()
    by_asset = _asset_lookup(assets)
    latest = _latest_by_asset(readings, "precipitation_pct_normal", PRECIP_SHORTFALL_WINDOW)

    alerts: list[AlertEvent] = []
    for aid, r in sorted(latest.items()):
        raw_value = r.get("value")
        if raw_value is None:
            continue
        try:
            pct = float(raw_value)
        except (TypeError, ValueError):
            continue
        if pct >= PRECIP_SHORTFALL_FLOOR:
            continue
        asset = by_asset.get(aid, {})
        muni = str(asset.get("municipality") or "")
        munis = [muni] if muni and muni.lower() not in {"unknown", ""} else ["(unscoped)"]
        lat, lon = asset.get("lat"), asset.get("lon")

        observed = str(r.get("observed_date") or "")
        date = "".join(ch for ch in observed[:10] if ch.isdigit())[:8] or "00000000"
        name = asset.get("asset_name") or aid

        linked_ids, sectors = link_impact(
            None, None, munis, index, radius_km=MODULE_RADIUS_KM["WEATHER_HAZARD"]
        )
        linked_ids = merge_asset_ids([aid] if aid in by_asset else None, linked_ids)
        sectors = sorted(set(sectors) | {"water"})

        alerts.append(
            AlertEvent(
                alert_id=f"AYL_ALR_{date}{PRECIP_MARKER}{_slug(aid)}",
                module_id="WEATHER_HAZARD",
                event_type="hazard",
                status="active",
                source_title=f"Precipitation shortfall ({pct:g}% of normal, 90d) — {name}",
                source_ref=r.get("source_ref") or "NOAA NCEI GHCN-Daily",
                source_hash=r.get("source_hash"),
                published_at=None,
                start_at=observed,
                end_at=None,
                asset_name=str(name),
                asset_id=aid if aid in by_asset else None,
                operator=asset.get("operator") or "NOAA NCEI",
                municipalities=munis,
                sectors_impacted=sectors,
                latitude=lat if isinstance(lat, (int, float)) else None,
                longitude=lon if isinstance(lon, (int, float)) else None,
                coord_confidence="approximate" if isinstance(lat, (int, float)) else "unknown",
                severity=1,
                confidence=60,
                ilap_score=None,
                covert_flags=[],
                gap_status="minor",
                review_status="needs_review",
                evidence_tier="T2",
                linked_asset_ids=linked_ids,
                validation_notes=(
                    f"Corroborating proxy: 90-day accumulated rainfall is {pct:g}% of the "
                    f"1991-2020 normal (below the {PRECIP_SHORTFALL_FLOOR:g}% "
                    "significantly-below-normal band). Not an official drought "
                    "classification on its own — compare against the USDM alert for this area."
                ),
            )
        )
    return alerts
