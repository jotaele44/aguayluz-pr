"""EPA Envirofacts UV index forecast adapter for the outdoor-conditions layer.

Input is ``getEnvirofactsUVDAILY/ZIP/{zip}/JSON``: a one-element list with the next-day
(or same-day) maximum UV index EPA publishes for that ZIP, computed from the NWS Climate
Prediction Center forecast::

    [{"ZIP_CODE": "00601", "CITY": "Adjuntas", "STATE": "PR",
      "UV_INDEX": "9", "UV_ALERT": "0", "DATE": "Oct/18/2026"}]

The forecast binds to the municipio the ZIP was chosen for only when EPA's own CITY
names that municipio (``AUTHORITATIVE_BINDING``); otherwise it is kept but UNRESOLVED.
Exposure categories are the EPA/WHO UV index scale.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

SOURCE_AUTHORITY = "U.S. EPA Envirofacts (UV index forecast, NWS Climate Prediction Center)"

#: EPA/WHO UV index exposure categories: (lowest index, label).
UV_CATEGORIES: tuple[tuple[int, str], ...] = (
    (0, "LOW"), (3, "MODERATE"), (6, "HIGH"), (8, "VERY_HIGH"), (11, "EXTREME"),
)


def uv_category(index: float | None) -> str | None:
    if index is None:
        return None
    label = None
    for floor, name in UV_CATEGORIES:
        if index >= floor:
            label = name
    return label


def parse_date(value: Any) -> date | None:
    """``Oct/18/2026`` -> date(2026, 10, 18)."""
    try:
        return datetime.strptime(str(value).strip(), "%b/%d/%Y").date()
    except ValueError:
        return None


def parse_daily(payload: Any) -> dict[str, Any] | None:
    """The one PR row of a UVDAILY response, normalized; None when there is none."""
    if not isinstance(payload, list):
        return None
    for row in payload:
        if not isinstance(row, dict) or str(row.get("STATE") or "").upper() != "PR":
            continue
        index: float | None
        try:
            index = float(row["UV_INDEX"])
        except (KeyError, TypeError, ValueError):
            index = None
        day = parse_date(row.get("DATE"))
        return {
            "zip": str(row.get("ZIP_CODE") or "") or None,
            "city": row.get("CITY"),
            "uv_index": index,
            "uv_category": uv_category(index),
            "uv_alert": str(row.get("UV_ALERT") or "0") == "1",
            "forecast_date": day.isoformat() if day else None,
            "raw": row,
        }
    return None


__all__ = ["SOURCE_AUTHORITY", "UV_CATEGORIES", "parse_daily", "parse_date", "uv_category"]
