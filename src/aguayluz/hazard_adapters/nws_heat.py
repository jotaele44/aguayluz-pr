"""NWS gridded heat-index adapter for the outdoor-conditions layer.

Input is ``GET /gridpoints/{wfo}/{x},{y}`` (the NDFD grid behind the forecast) for the
cell holding a municipio's Census internal point. The grid publishes hourly-or-longer
intervals as ``{"validTime": "<start>/<ISO 8601 duration>", "value": <degC>}``.

The run keeps the maximum heat index (and wet-bulb globe temperature, and maximum air
temperature) over intervals that overlap the next 24 and 48 hours, converted to °F and
banded on the NWS heat-index chart. Those bands are the national chart, not WFO San
Juan's advisory criteria: an actual Heat Advisory arrives through
``scripts/ingest_nws_alerts.py`` and is what the alert layer acts on.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

SOURCE_AUTHORITY = "NOAA/NWS Weather Forecast Office San Juan (NDFD grid)"

#: NWS heat-index chart, °F: (lowest value, band).
HEAT_BANDS: tuple[tuple[float, str], ...] = (
    (80.0, "CAUTION"), (90.0, "EXTREME_CAUTION"), (103.0, "DANGER"), (125.0, "EXTREME_DANGER"),
)
BELOW_CAUTION = "BELOW_CAUTION"

_DURATION_RE = re.compile(r"^P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?)?$")


def heat_band(value_f: float | None) -> str | None:
    if value_f is None:
        return None
    band = BELOW_CAUTION
    for floor, name in HEAT_BANDS:
        if value_f >= floor:
            band = name
    return band


def c_to_f(value: float | None) -> float | None:
    return round(value * 9 / 5 + 32, 1) if value is not None else None


def parse_interval(valid_time: str) -> tuple[datetime, datetime] | None:
    """``2026-10-18T10:00:00+00:00/PT1H`` -> (start, end)."""
    try:
        start_raw, duration = str(valid_time).split("/", 1)
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    match = _DURATION_RE.match(duration)
    if not match or not any(match.groupdict().values()):
        return None
    length = timedelta(days=int(match.group("d") or 0), hours=int(match.group("h") or 0),
                       minutes=int(match.group("m") or 0))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start, start + length


def window_max(series: dict[str, Any] | None, start: datetime, end: datetime) -> tuple[float | None, str | None]:
    """Max value (in the series' unit) over intervals overlapping [start, end), and when."""
    best: tuple[float | None, str | None] = (None, None)
    for item in (series or {}).get("values") or []:
        value = item.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        interval = parse_interval(item.get("validTime"))
        if interval is None or interval[1] <= start or interval[0] >= end:
            continue
        if best[0] is None or value > best[0]:
            best = (float(value), interval[0].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"))
    return best


def _uom_is_celsius(series: dict[str, Any] | None) -> bool:
    return str((series or {}).get("uom") or "").endswith("degC")


def summarize(properties: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Heat summary for the next 24 h and 48 h from one gridpoint's properties."""
    out: dict[str, Any] = {"update_time": properties.get("updateTime")}
    for label, hours in (("24h", 24), ("48h", 48)):
        end = now + timedelta(hours=hours)
        for field, key in (("heatIndex", "heat_index"), ("wetBulbGlobeTemperature", "wbgt"),
                           ("maxTemperature", "max_temp")):
            series = properties.get(field)
            value, at = window_max(series, now, end)
            if value is not None and not _uom_is_celsius(series):
                raise ValueError(f"{field} unit {(series or {}).get('uom')!r} is not degC")
            out[f"{key}_max_f_{label}"] = c_to_f(value)
            if key == "heat_index":
                out[f"heat_index_peak_at_{label}"] = at
        out[f"heat_band_{label}"] = heat_band(out[f"heat_index_max_f_{label}"])
    return out


__all__ = [
    "BELOW_CAUTION",
    "HEAT_BANDS",
    "SOURCE_AUTHORITY",
    "c_to_f",
    "heat_band",
    "parse_interval",
    "summarize",
    "window_max",
]
