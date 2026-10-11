"""Stage IV Puerto Rico rainfall (QPE) adapter for the NWS hydromet plane.

Input is one municipio's summary of one NWPS Stage IV PR GeoTIFF window
(``nws_precip_{window}_{yyyymmdd}_pr.tif``): mean and max observed rainfall over the
HRAP cells assigned to the municipio, the PRISM normal and the cell count. The ingest
freezes the GeoTIFF bytes and computes the summary; this module only shapes it into a
``HazardRecord``.

One canonical event per municipio × window × 12Z-12Z data day. If NWS re-processes a
file, the new values supersede the earlier record for that same event.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus

SOURCE_AUTHORITY = "NOAA/NWS River Forecast Centers (Stage IV via NWPS)"
CANONICAL_PREFIX = "STAGEIV_QPE:"
HAZARD_TYPE = "PRECIPITATION_ACCUMULATION"

#: Window name in the NWPS file name → number of 12Z-12Z days it accumulates.
WINDOW_DAYS: dict[str, int] = {"1day": 1, "last7days": 7, "last30days": 30}

#: 1-day municipio mean (inches) that counts as heavy rain (alert severity 2).
HEAVY_RAIN_MEAN_IN = 3.0

#: 1-day single-cell maximum (inches) that counts as heavy rain at severity 3.
HEAVY_RAIN_CELL_MAX_IN = 6.0


def parse_data_time(value: Any) -> datetime | None:
    """GDAL ``data_time`` tag (``20261009T12:00:00``), the window's closing 12Z."""
    text = str(value or "").strip()
    for fmt in ("%Y%m%dT%H:%M:%S", "%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def window_bounds(window: str, data_time: datetime) -> tuple[datetime, datetime]:
    days = WINDOW_DAYS[window]
    return data_time - timedelta(days=days), data_time


def canonical_event_id(window: str, geoid: str, data_date: date) -> str:
    return f"{CANONICAL_PREFIX}{window}:{geoid}:{data_date:%Y%m%d}"


def values_digest(values: dict[str, Any]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def stable_record_id(event_id: str, values: dict[str, Any], supersedes_record_id: str | None) -> str:
    chained = sha256(f"{values_digest(values)}|{supersedes_record_id or 'HEAD'}".encode()).hexdigest()
    return f"{event_id}:REV:{chained[:20]}"


def _round(value: float | None, places: int = 3) -> float | None:
    return None if value is None else round(float(value), places)


def zone_values(
    *,
    obs_mean: float | None,
    obs_max: float | None,
    normal_mean: float | None,
    cell_count: int,
    normal_cell_count: int,
) -> dict[str, Any]:
    """Normalized rainfall values for one municipio (inches; percent of normal)."""
    pct = None
    departure = None
    if obs_mean is not None and normal_mean:
        pct = obs_mean / normal_mean * 100.0
        departure = obs_mean - normal_mean
    return {
        "obs_mean_in": _round(obs_mean),
        "obs_max_in": _round(obs_max),
        "normal_mean_in": _round(normal_mean),
        "departure_mean_in": _round(departure),
        "pct_of_normal": _round(pct, 1),
        "cell_count": int(cell_count),
        "normal_cell_count": int(normal_cell_count),
    }


def heavy_rain_severity(values: dict[str, Any]) -> int | None:
    """Alert severity for one municipio's 1-day values, or None below both thresholds.

    Used by the heavy-rain promoter and by the API to flag rows; meaningful for the
    ``1day`` window only.
    """
    mean, peak = values.get("obs_mean_in"), values.get("obs_max_in")
    if isinstance(peak, (int, float)) and peak >= HEAVY_RAIN_CELL_MAX_IN:
        return 3
    if isinstance(mean, (int, float)) and mean >= HEAVY_RAIN_MEAN_IN:
        return 2
    return None


def normalize(
    values: dict[str, Any],
    manifestation_id: str,
    *,
    window: str,
    geoid: str,
    municipio: str,
    data_time: datetime,
    source_file: str,
    method: str,
    source_url: str | None = None,
    supersedes_record_id: str | None = None,
) -> HazardRecord:
    """Shape one municipio × window summary into a HYDROMETEOROLOGY observation."""
    start, end = window_bounds(window, data_time)
    event_id = canonical_event_id(window, geoid, end.date())
    days = WINDOW_DAYS[window]
    resolved = values.get("obs_mean_in") is not None and values.get("cell_count", 0) > 0
    return HazardRecord(
        record_id=stable_record_id(event_id, values, supersedes_record_id),
        canonical_event_id=event_id,
        record_kind=RecordKind.OBSERVATION,
        family=HazardFamily.HYDROMETEOROLOGY,
        hazard_type=HAZARD_TYPE,
        source_authority=SOURCE_AUTHORITY,
        source_record_id=f"{source_file}#{geoid}",
        manifestation_id=manifestation_id,
        title_raw=f"{municipio}: {days}-day Stage IV rainfall ending {end:%Y-%m-%d} 12Z",
        normalized_label=municipio,
        status=RecordStatus.PROVISIONAL if resolved else RecordStatus.UNRESOLVED,
        observed_from=start,
        observed_to=end,
        municipality_id=geoid if resolved else None,
        geography_basis=f"HRAP_GRID:{method}",
        geometry_precision="RASTER_ZONAL_SUMMARY",
        provisional=True,
        supersedes_record_id=supersedes_record_id,
        raw_attributes={
            "file": source_file,
            "window": window,
            "data_time": data_time.isoformat(),
            **({"url": source_url} if source_url else {}),
        },
        normalized_values={
            "window": window,
            "window_days": days,
            "data_date": f"{end:%Y-%m-%d}",
            "municipio": municipio,
            "method": method,
            **values,
            "values_digest": values_digest(values),
        },
    )
