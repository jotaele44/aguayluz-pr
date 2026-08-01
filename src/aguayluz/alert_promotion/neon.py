"""Promote NEON publication events into AlertEvents.

``scripts/ingest_neon.py`` diffs the ``availableMonths[]`` array NEON exposes for
every site/product pair and writes typed change records to
``data/neon_publication_events.jsonl``. This promoter turns those into validated
:class:`~aguayluz.alerts.AlertEvent` rows, so a new stream-chemistry release at Río
Cupeyes or a sensor that stopped publishing at Río Yahuecas surfaces on the alert
layer instead of sitting in a registry file nobody reads.

Module routing. ``schemas/alert_event.schema.json`` pins ``module_id`` to a closed
ten-value enum, so there is no "data publication" module to add — these events land
on existing ones by what the product measures:

* water chemistry / nitrate / dissolved gases -> ``CONTAMINATION``
* discharge / surface-water elevation         -> ``HYDRO_OPS``
* precipitation / meteorology                 -> ``WEATHER_HAZARD``
* a feed that stopped publishing              -> ``TELECOM_SCADA``

``TELECOM_SCADA`` was seeded dormant with the charter "telemetry and control loss at
remote infrastructure". A NEON sensor that has not published in months is exactly
that, so this feed activates it — the same way the USGS earthquake ingest activated
``SEISMIC_GEO``.

Severity stays at each module's floor and never reaches ``CRITICAL_SEVERITY`` (4):
a data-publication event is an operator signal, not a life-safety one, and must not
trigger push/SMS fan-out.

Pure functions only (no I/O, no wall-clock). Real T1 NEON metadata in, real alert out.
"""

from __future__ import annotations

from typing import Any, cast

from ..alerts import AlertEvent, CoordConfidence, ModuleId
from ..impact import (
    MODULE_RADIUS_KM,
    AssetIndex,
    in_alert_bounds,
    link_impact,
    merge_asset_ids,
)
from ..neon.mapping import FEED_HEALTH_MODULE, alert_module_for, sanitize_code
from ..water_alerts import _slug

NEON_MARKER = "_neonpub_"

#: Change types this promoter emits alerts for. ``new_product`` is deliberately
#: included: NEON adding a product at a PR site is a genuine new observation vector.
_ALERTABLE: frozenset[str] = frozenset({
    "new_month", "backfilled_month", "new_release", "new_product", "publication_gap",
})

#: Per-change-type presentation: (event_type, severity, headline verb).
#: Severities sit at each module's floor — see the module docstring on why none reach 4.
_CHANGE_SPEC: dict[str, dict[str, Any]] = {
    "new_month": {
        "event_type": "quality", "severity": 2,
        "verb": "New monthly release",
    },
    "backfilled_month": {
        "event_type": "quality", "severity": 2,
        "verb": "Historical data corrected",
    },
    "new_release": {
        "event_type": "quality", "severity": 1,
        "verb": "New NEON release tag",
    },
    "new_product": {
        "event_type": "quality", "severity": 1,
        "verb": "New data product",
    },
    "publication_gap": {
        "event_type": "failure", "severity": 2,
        "verb": "Publication gap",
    },
}

#: Municipality per NEON site. Resolved by point-in-polygon in
#: ``scripts/ingest_neon.py``; repeated here because this promoter is pure and
#: receives only the change record, which carries coordinates but no municipality.
_SITE_MUNICIPALITY: dict[str, str] = {
    "CUPE": "San Germán",
    "GUAN": "Guánica",
    "GUIL": "Adjuntas",
    "LAJA": "Lajas",
}


def _event_date(record: dict[str, Any]) -> str:
    """YYYYMMDD for the alert_id, from the published month (not the detection time).

    Anchoring on the month keeps the id stable across re-detections, so the
    idempotent merge in ``scripts/build_alerts.py`` replaces the row instead of
    accumulating a new one per run.
    """
    month = str(record.get("latest_month") or "")
    digits = "".join(ch for ch in month if ch.isdigit())
    if len(digits) >= 6:
        return f"{digits[:6]}01"
    detected = "".join(ch for ch in str(record.get("detected_at") or "")[:10] if ch.isdigit())
    return detected[:8] if len(detected) >= 8 else "00000000"


def neon_alert(
    record: dict[str, Any],
    geo: dict[str, dict[str, Any]] | None = None,
    index: AssetIndex | None = None,
) -> AlertEvent | None:
    """Project one NEON publication-change record into an AlertEvent."""
    index = index or AssetIndex()
    change_type = str(record.get("change_type") or "")
    if change_type not in _ALERTABLE:
        return None

    site = str(record.get("neon_site") or "")
    product_code = str(record.get("product_code") or "")
    if not site or not product_code:
        return None

    spec = _CHANGE_SPEC[change_type]
    habitat = str(record.get("habitat") or "aquatic")
    if change_type == "publication_gap":
        resolved: str | None = FEED_HEALTH_MODULE
    else:
        resolved = alert_module_for(product_code, habitat)
    # No module means the product is out of scope for this producer — NEON publishes
    # ~80 products per site, most of them ecological research (phenology, mosquito
    # trapping) with no water/power bearing. Those stay in the availability registry
    # but must not reach the alert layer.
    if resolved is None:
        return None
    # Every routed value comes from the alert_event module enum; the mapping table is
    # typed as plain str, so narrow here rather than leaking `str` into AlertEvent.
    module: ModuleId = cast("ModuleId", resolved)

    lat_raw, lon_raw = record.get("lat"), record.get("lon")
    lat: float | None = None
    lon: float | None = None
    coord_confidence: CoordConfidence = "unknown"
    # isinstance first: change records come from JSON, so a missing coordinate is None
    # and in_alert_bounds alone does not narrow the type for the float() calls.
    if (
        isinstance(lat_raw, (int, float))
        and isinstance(lon_raw, (int, float))
        and in_alert_bounds(lat_raw, lon_raw)
    ):
        lat = round(float(lat_raw), 6)
        lon = round(float(lon_raw), 6)
        coord_confidence = "exact"

    muni = _SITE_MUNICIPALITY.get(site)
    munis = [muni] if muni else ["(unscoped)"]
    linked, sectors = link_impact(
        lat, lon, munis, index, radius_km=MODULE_RADIUS_KM.get(module)
    )

    site_name = str(record.get("site_name") or site)
    product_title = str(record.get("product_title") or product_code)
    month = record.get("latest_month") or "unknown month"

    if change_type == "publication_gap":
        behind = record.get("months_behind")
        detail = f"no publication since {month}"
        if isinstance(behind, int):
            detail += f" ({behind} months)"
        notes = (
            f"NEON {product_code} at {site} has not published in {behind} month(s); "
            "possible sensor outage or upstream processing hold. Derived from the "
            "availableMonths array on the NEON /sites endpoint."
        )
    elif change_type == "backfilled_month":
        detail = f"historical months revised (latest still {month})"
        notes = (
            "The NEON availableMonths hash changed while latest_month did not — a "
            "previously published month was corrected or re-released."
        )
    elif change_type == "new_release":
        detail = f"{record.get('previous_release') or 'none'} -> {record.get('latest_release')}"
        notes = "NEON issued a new annual RELEASE tag covering this site's products."
    else:
        detail = f"through {month}"
        notes = (
            f"Derived from the NEON availableMonths array ({record.get('month_count')} "
            f"months available). Publication event, not an operational disruption."
        )

    alert_id = (
        f"AYL_ALR_{_event_date(record)}{NEON_MARKER}"
        f"{_slug(site)}_{sanitize_code(product_code)}_{_slug(change_type, 20)}"
    )

    return AlertEvent(
        alert_id=alert_id,
        module_id=module,
        event_type=spec["event_type"],
        status="active",
        source_title=f"NEON {spec['verb']}: {product_title} at {site_name} — {detail}",
        source_ref=record.get("source_ref") or f"NEON API v0 /sites/{site}",
        source_hash=record.get("source_hash"),
        published_at=record.get("release_generated_at"),
        start_at=str(record.get("detected_at") or record.get("release_generated_at") or ""),
        end_at=None,
        asset_name=site_name,
        asset_id=f"NEON_{site}",
        operator="NSF NEON",
        municipalities=munis,
        sectors_impacted=sectors,
        latitude=lat,
        longitude=lon,
        coord_confidence=coord_confidence,
        severity=int(spec["severity"]),
        confidence=int(record.get("confidence") or 80),
        ilap_score=None,
        covert_flags=[],
        gap_status="none",
        review_status="accepted",
        evidence_tier=record.get("evidence_tier") or "T1",
        linked_asset_ids=merge_asset_ids([f"NEON_{site}"], linked),
        validation_notes=notes,
    )


def neon_alerts(
    records: list[dict[str, Any]],
    geo: dict[str, dict[str, Any]] | None = None,
    index: AssetIndex | None = None,
) -> list[AlertEvent]:
    """Promote every NEON publication-change record into an AlertEvent."""
    out: list[AlertEvent] = []
    for rec in records or []:
        alert = neon_alert(rec, geo, index)
        if alert is not None:
            out.append(alert)
    return out
