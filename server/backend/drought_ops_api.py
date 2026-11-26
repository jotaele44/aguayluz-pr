"""Read-only API for the Puerto Rico USDM drought operations surface."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aguayluz import DATA_DIR as AGUAYLUZ_DATA_DIR

router = APIRouter(tags=["drought-operations"])

DATA_DIR: Path = AGUAYLUZ_DATA_DIR
CURRENT_FILE = "drought_usdm_footprint.json"
MUNICIPIO_FILE = "drought_conditions.jsonl"
CATEGORIES = ("D0", "D1", "D2", "D3", "D4")
FRESH_DAYS = 10


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _parse_date(value: Any) -> date | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _freshness(map_date: Any, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).date()
    observed = _parse_date(map_date)
    if observed is None:
        return {"state": "UNKNOWN", "age_days": None, "max_age_days": FRESH_DAYS}
    age = (current - observed).days
    return {
        "state": "FRESH" if 0 <= age <= FRESH_DAYS else "STALE",
        "age_days": age,
        "max_age_days": FRESH_DAYS,
    }


def _latest_municipios(rows: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    dated = [row for row in rows if _parse_date(row.get("observed_date"))]
    if not dated:
        return None, []
    latest_date = max(str(row.get("observed_date"))[:10] for row in dated)
    latest_by_fips: dict[str, dict[str, Any]] = {}
    for row in dated:
        if str(row.get("observed_date"))[:10] != latest_date:
            continue
        fips = str(row.get("site_no") or "")
        if not fips:
            continue
        latest_by_fips[fips] = row
    result = []
    for fips, row in sorted(latest_by_fips.items()):
        value = row.get("value")
        try:
            ordinal = int(float(value))
        except (TypeError, ValueError):
            ordinal = -1
        category = f"D{ordinal}" if 0 <= ordinal <= 4 else "None"
        asset_name = str(row.get("asset_name") or "")
        municipio = asset_name.removesuffix(" (USDM drought monitoring area)") or row.get("municipality")
        result.append({
            "geoid": fips,
            "municipio": municipio,
            "category": category,
            "ordinal": ordinal,
            "observed_date": latest_date,
            "evidence_tier": row.get("evidence_tier", "T1"),
            "provisional": row.get("provisional"),
        })
    return latest_date, result


def _change(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(history) < 2:
        return None
    previous, current = history[-2], history[-1]
    delta = {}
    for category in CATEGORIES:
        try:
            delta[category] = round(float(current[category]) - float(previous[category]), 2)
        except (KeyError, TypeError, ValueError):
            delta[category] = None
    severity_delta = next(
        (delta[key] for key in ("D4", "D3", "D2", "D1", "D0") if delta.get(key) not in (None, 0)),
        0,
    )
    direction = "unchanged"
    if severity_delta and severity_delta > 0:
        direction = "worsened"
    elif severity_delta and severity_delta < 0:
        direction = "improved"
    return {
        "from_map_date": previous.get("map_date"),
        "to_map_date": current.get("map_date"),
        "delta_percentage_points": delta,
        "direction": direction,
        "basis": "highest-severity non-zero cumulative category delta; descriptive only",
    }


def _unavailable() -> dict[str, Any]:
    return {
        "schema_version": "aguayluz.drought-operations-api/v0.1",
        "status": "unavailable",
        "map_date": None,
        "freshness": {"state": "UNKNOWN", "age_days": None, "max_age_days": FRESH_DAYS},
        "statistics": None,
        "history": [],
        "change": None,
        "municipio_date": None,
        "municipios": [],
        "source_manifestations": {},
        "limitations": [
            "No committed USDM footprint artifact is available yet.",
            "Unavailable data is never interpreted as no drought.",
        ],
    }


def drought_summary_document(now: datetime | None = None) -> dict[str, Any]:
    current = _read_json(DATA_DIR / CURRENT_FILE)
    if current is None:
        return _unavailable()
    history = current.get("history") if isinstance(current.get("history"), list) else []
    municipio_date, municipios = _latest_municipios(_read_jsonl(DATA_DIR / MUNICIPIO_FILE))
    return {
        "schema_version": "aguayluz.drought-operations-api/v0.1",
        "status": "available",
        "map_date": current.get("map_date"),
        "retrieved_at": current.get("retrieved_at"),
        "authority": current.get("authority"),
        "evidence_tier": current.get("evidence_tier"),
        "freshness": _freshness(current.get("map_date"), now),
        "statistics": current.get("statistics"),
        "history": history,
        "change": _change(history),
        "municipio_date": municipio_date,
        "municipios": municipios,
        "source_manifestations": current.get("source_manifestations") or {},
        "limitations": current.get("limitations") or [],
    }


@router.get("/drought/summary")
def drought_summary() -> JSONResponse:
    return JSONResponse(drought_summary_document())


@router.get("/drought/footprint.geojson")
def drought_footprint() -> JSONResponse:
    current = _read_json(DATA_DIR / CURRENT_FILE)
    if current is None:
        return JSONResponse({
            "type": "FeatureCollection",
            "features": [],
            "status": "unavailable",
            "map_date": None,
            "freshness": {"state": "UNKNOWN", "age_days": None, "max_age_days": FRESH_DAYS},
        })
    footprint = current.get("footprint")
    if not isinstance(footprint, dict) or footprint.get("type") != "FeatureCollection":
        footprint = {"type": "FeatureCollection", "features": []}
    return JSONResponse({
        **footprint,
        "status": "available" if footprint.get("features") else "unavailable",
        "map_date": current.get("map_date"),
        "retrieved_at": current.get("retrieved_at"),
        "freshness": _freshness(current.get("map_date")),
        "provenance": (current.get("source_manifestations") or {}).get("geometry"),
    })
