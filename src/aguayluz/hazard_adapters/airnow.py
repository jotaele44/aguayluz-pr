"""AirNow current-observation adapter for the outdoor-conditions layer.

Input is ``GET /aq/observation/latLong/current/`` (needs an API key): one row per
reporting area and pollutant near the query point, per AirNow's published format::

    {"DateObserved": "2026-10-18 ", "HourObserved": 13, "LocalTimeZone": "AST",
     "ReportingArea": "San Juan", "StateCode": "PR", "Latitude": 18.42,
     "Longitude": -66.07, "ParameterName": "PM2.5", "AQI": 38,
     "Category": {"Number": 1, "Name": "Good"}}

AirNow data are preliminary and unvalidated; AirNow asks that they not be used for
regulatory decisions. Saharan dust episodes show up here as PM10/PM2.5.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

SOURCE_AUTHORITY = "U.S. EPA AirNow"

#: AirNow / EPA AQI categories by number.
AQI_CATEGORIES: dict[int, str] = {
    1: "GOOD", 2: "MODERATE", 3: "UNHEALTHY_FOR_SENSITIVE_GROUPS", 4: "UNHEALTHY",
    5: "VERY_UNHEALTHY", 6: "HAZARDOUS", 7: "UNAVAILABLE",
}
_TZ_OFFSETS = {"AST": -4, "EST": -5, "EDT": -4, "UTC": 0, "GMT": 0}


def category(row: dict[str, Any]) -> str | None:
    number = (row.get("Category") or {}).get("Number")
    return AQI_CATEGORIES.get(number) if isinstance(number, int) else None


def observed_at(row: dict[str, Any]) -> datetime | None:
    try:
        day = datetime.strptime(str(row.get("DateObserved") or "").strip(), "%Y-%m-%d")
        hour = int(row.get("HourObserved"))
    except (TypeError, ValueError):
        return None
    offset = _TZ_OFFSETS.get(str(row.get("LocalTimeZone") or "").strip().upper())
    if offset is None:
        return None
    local = day.replace(hour=hour, tzinfo=timezone(timedelta(hours=offset)))
    return local.astimezone(timezone.utc)


def classify(row: Any) -> str:
    if not isinstance(row, dict):
        return "unresolved:not_an_object"
    if not row.get("ReportingArea") or not row.get("ParameterName"):
        return "unresolved:missing_area_or_parameter"
    if not isinstance(row.get("AQI"), (int, float)) or row.get("AQI") < 0:
        return "unresolved:missing_aqi"
    if str(row.get("StateCode") or "").upper() != "PR":
        return f"excluded:state_{str(row.get('StateCode') or 'blank').lower()}"
    return "retained"


__all__ = ["AQI_CATEGORIES", "SOURCE_AUTHORITY", "category", "classify", "observed_at"]
