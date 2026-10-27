"""NDBC latest-observation adapter for the outdoor-conditions layer.

Input is ``https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt``: one whitespace-
delimited row per station with its most recent report, two ``#`` header rows (names,
units). The Puerto Rico buoys are operated by CARICOOS and distributed by NDBC.

``MM`` is NDBC's "missing" marker — the sensor reported nothing. It is carried as
``None`` and never read as calm water or zero wind. Raw strings are kept next to the
normalized values so a conversion can always be checked against what NDBC published.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SOURCE_AUTHORITY = "NOAA National Data Buoy Center"

#: The Puerto Rico buoys (NDBC activestations.xml, owner CARICOOS). Names are NDBC's.
STATIONS: dict[str, dict[str, Any]] = {
    "41053": {"name": "San Juan, PR", "lat": 18.474, "lon": -66.099},
    "41056": {"name": "Vieques Island, PR", "lat": 18.261, "lon": -65.464},
    "41115": {"name": "Rincon, Puerto Rico (CDIP 181)", "lat": 18.376, "lon": -67.28},
    "41121": {"name": "Arecibo, Puerto Rico (CDIP 249)", "lat": 18.491, "lon": -66.701},
    "42085": {"name": "Southeast of Ponce, PR", "lat": 17.87, "lon": -66.537},
}

MISSING = "MM"
M_TO_FT = 3.28084
MS_TO_KT = 1.943844


def parse_latest_obs(text: str) -> tuple[list[str], list[list[str]], list[str]]:
    """(column names, data rows, malformed lines) from latest_obs.txt."""
    lines = text.splitlines()
    header = next((ln for ln in lines if ln.startswith("#")), None)
    if header is None:
        raise ValueError("latest_obs has no header row")
    columns = header.lstrip("#").split()
    if columns[:3] != ["STN", "LAT", "LON"]:
        raise ValueError(f"unexpected latest_obs header: {columns[:5]}")
    rows: list[list[str]] = []
    malformed: list[str] = []
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != len(columns):
            malformed.append(line[:80])
            continue
        rows.append(parts)
    return columns, rows, malformed


def _num(raw: str | None) -> float | None:
    if raw is None or raw == MISSING:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def observed_at(row: dict[str, str]) -> datetime | None:
    try:
        return datetime(int(row["YYYY"]), int(row["MM"]), int(row["DD"]),
                        int(row["hh"]), int(row["mm"]), tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None


def normalize_row(row: dict[str, str]) -> dict[str, Any]:
    """Normalized observation; every value None when NDBC reported ``MM``."""
    wvht_m = _num(row.get("WVHT"))
    wspd = _num(row.get("WSPD"))
    gst = _num(row.get("GST"))
    wtmp = _num(row.get("WTMP"))
    atmp = _num(row.get("ATMP"))

    def r(value: float | None, places: int = 1) -> float | None:
        return round(value, places) if value is not None else None

    return {
        "wave_height_m": wvht_m,
        "wave_height_ft": r(wvht_m * M_TO_FT if wvht_m is not None else None),
        "dominant_period_s": _num(row.get("DPD")),
        "average_period_s": _num(row.get("APD")),
        "mean_wave_direction_deg": _num(row.get("MWD")),
        "wind_direction_deg": _num(row.get("WDIR")),
        "wind_speed_ms": wspd,
        "wind_speed_kt": r(wspd * MS_TO_KT if wspd is not None else None),
        "wind_gust_kt": r(gst * MS_TO_KT if gst is not None else None),
        "water_temp_c": wtmp,
        "water_temp_f": r(wtmp * 9 / 5 + 32 if wtmp is not None else None),
        "air_temp_c": atmp,
        "pressure_hpa": _num(row.get("PRES")),
    }


__all__ = [
    "MISSING",
    "SOURCE_AUTHORITY",
    "STATIONS",
    "normalize_row",
    "observed_at",
    "parse_latest_obs",
]
