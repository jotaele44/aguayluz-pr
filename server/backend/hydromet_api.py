"""API for the NWS hydromet plane (NWPS gauges, Stage IV rainfall; later cones/outlooks).

Reads only the committed files written by the ``scripts/ingest_*`` hydromet producers;
imports nothing heavier than pydantic so the gui-parity CI backend boots without the
geospatial stack. ``POST /hydromet/refresh/{source_id}`` is the one write path: it runs
the source's ingest in-process (the same way ``POST /admin/run-export`` runs the
exporter, so it also works in the frozen desktop bundle), then rebuilds alerts.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from aguayluz.hazard_adapters import stage_iv_qpe
from aguayluz.hazard_adapters.nwps_gauges import FLOOD_CATEGORIES, parse_time
from aguayluz.hazard_plane import current_records
from aguayluz.hydromet import store
from server.backend import main as legacy

router = APIRouter(tags=["hydromet"])

#: Resolved per request so tests (and AGUAYLUZ_DATA_HOME) can redirect it.
DATA_DIR: Path = legacy.DATA
SCRIPTS: Path = legacy.SCRIPTS

SCOPE_STATEMENT = (
    "NOAA/NWS hydrometeorological observations and outlooks for Puerto Rico, frozen with "
    "byte SHA-256 provenance. A gauge above a flood threshold or a heavy-rain municipio is "
    "an observed hazard condition, not confirmed damage or service impact; bindings to "
    "assets and municipios carry their evidence class."
)

_refresh_lock = threading.Lock()
_refresh_state: dict[str, Any] = {"running": False, "source_id": None, "started_at": None,
                                  "finished_at": None, "last_result": None}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _registry() -> dict[str, Any]:
    return store.load_source_registry()


def _source_rows(now: datetime) -> list[dict[str, Any]]:
    registry = _registry()
    receipts = store.load_receipts(DATA_DIR).get("sources", {})
    rows = []
    for source in registry.get("sources", []):
        receipt = receipts.get(source.get("source_id"))
        rows.append({
            **source,
            "receipt": receipt,
            "freshness": store.freshness(receipt, source, now),
        })
    return rows


def _gauge_rows(now: datetime) -> list[dict[str, Any]]:
    source = store.registry_source("nwps_gauges", _registry()) or {}
    stale_after = float(source.get("observation_stale_after_seconds") or 21600)
    rows = []
    for row in store.load_gauge_state(DATA_DIR):
        valid = parse_time((row.get("observed") or {}).get("valid_time"))
        item = {k: v for k, v in row.items() if k != "detail"}
        item["flooding"] = row.get("flood_category") in FLOOD_CATEGORIES
        item["observation_age_seconds"] = (now - valid).total_seconds() if valid else None
        item["observation_stale"] = valid is None or (now - valid).total_seconds() > stale_after
        rows.append(item)
    return rows


def _rainfall_records(records: list[Any], window: str) -> dict[str, list[Any]]:
    """Current Stage IV records for ``window``, grouped by data date (YYYY-MM-DD)."""
    by_date: dict[str, list[Any]] = {}
    for record in store.current_by_event(records, stage_iv_qpe.CANONICAL_PREFIX).values():
        values = record.normalized_values
        if values.get("window") == window and values.get("data_date"):
            by_date.setdefault(str(values["data_date"]), []).append(record)
    return by_date


def _rainfall_row(record: Any, window: str) -> dict[str, Any]:
    values = record.normalized_values
    return {
        "geoid": record.municipality_id or record.source_record_id.rsplit("#", 1)[-1],
        "municipio": values.get("municipio") or record.normalized_label,
        "data_date": values.get("data_date"),
        "observed_from": _iso(record.observed_from) if record.observed_from else None,
        "observed_to": _iso(record.observed_to) if record.observed_to else None,
        **{key: values.get(key) for key in (
            "obs_mean_in", "obs_max_in", "normal_mean_in", "departure_mean_in",
            "pct_of_normal", "cell_count", "method",
        )},
        "status": record.status.value,
        "heavy_rain_severity": stage_iv_qpe.heavy_rain_severity(values) if window == "1day" else None,
        "record_id": record.record_id,
        "manifestation_id": record.manifestation_id,
    }


@router.get("/hydromet/summary")
def hydromet_summary() -> JSONResponse:
    now = _now()
    records = store.load_records(DATA_DIR)
    integrity = store.integrity(DATA_DIR)
    gauges = _gauge_rows(now)
    rain_days = _rainfall_records(records, "1day")
    rain_date = max(rain_days) if rain_days else None
    rain_latest = [_rainfall_row(r, "1day") for r in rain_days.get(rain_date or "", [])]
    categories: dict[str, int] = {}
    for row in gauges:
        key = row.get("flood_category") or "blank"
        categories[key] = categories.get(key, 0) + 1
    return JSONResponse({
        "scope": {"statement": SCOPE_STATEMENT, "completeness_claimed": False},
        "generated_at": _iso(now),
        "sources": [
            {
                "source_id": s.get("source_id"),
                "label": s.get("label"),
                "freshness": s["freshness"],
                "last_attempt_utc": (s["receipt"] or {}).get("last_attempt_utc"),
                "last_status": (s["receipt"] or {}).get("last_status"),
            }
            for s in _source_rows(now)
        ],
        "counts": {
            "records": len(records),
            "current_records": len(current_records(records)),
            "relationships": integrity["counts"]["relationships"],
            "manifestations": integrity["counts"]["manifestations"],
            "gauges": len(gauges),
            "gauges_in_flood": sum(1 for g in gauges if g["flooding"]),
            "gauges_stale": sum(1 for g in gauges if g["observation_stale"]),
            "rainfall_zones": len(rain_latest),
            "rainfall_heavy": sum(1 for r in rain_latest if r["heavy_rain_severity"]),
        },
        "rainfall_latest_date": rain_date,
        "flood_categories": dict(sorted(categories.items())),
        "integrity": {"state": integrity["state"], "unresolved": integrity["unresolved"]},
    })


@router.get("/hydromet/sources")
def hydromet_sources() -> JSONResponse:
    registry = _registry()
    return JSONResponse({
        "schema_version": registry.get("schema_version"),
        "scope": registry.get("scope"),
        "legacy_catalog": registry.get("legacy_catalog"),
        "sources": _source_rows(_now()),
    })


@router.get("/hydromet/gauges")
def hydromet_gauges(
    flooding_only: bool = Query(False),
    municipio: str | None = Query(None),
) -> JSONResponse:
    rows = _gauge_rows(_now())
    if flooding_only:
        rows = [r for r in rows if r["flooding"]]
    if municipio:
        wanted = municipio.casefold()
        rows = [r for r in rows if str(r.get("municipio") or r.get("county_raw") or "").casefold() == wanted]
    order = {c: i for i, c in enumerate(reversed(FLOOD_CATEGORIES))}
    rows.sort(key=lambda r: (order.get(r.get("flood_category"), len(order)), str(r.get("name") or "")))
    return JSONResponse({"total": len(rows), "items": rows})


@router.get("/hydromet/gauges.geojson")
def hydromet_gauges_geojson() -> JSONResponse:
    features = []
    for row in _gauge_rows(_now()):
        lat, lon = row.get("latitude"), row.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        observed = row.get("observed") or {}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "lid": row.get("lid"),
                "name": row.get("name"),
                "flood_category": row.get("flood_category"),
                "flooding": row["flooding"],
                "observation_stale": row["observation_stale"],
                "stage": observed.get("stage"),
                "stage_unit": observed.get("stage_unit"),
                "valid_time": observed.get("valid_time"),
                "municipio": row.get("municipio"),
                "asset_id": row.get("asset_id"),
                "binding_evidence": row.get("binding_evidence"),
            },
        })
    return JSONResponse({"type": "FeatureCollection", "features": features})


@router.get("/hydromet/rainfall")
def hydromet_rainfall(
    window: str = Query("1day"),
    date: str | None = Query(None, description="data day YYYY-MM-DD; default: latest"),
) -> JSONResponse:
    """Stage IV rainfall per municipio for one window and 12Z-12Z data day."""
    if window not in stage_iv_qpe.WINDOW_DAYS:
        raise HTTPException(status_code=422, detail=f"window must be one of {list(stage_iv_qpe.WINDOW_DAYS)}")
    by_date = _rainfall_records(store.load_records(DATA_DIR), window)
    dates = sorted(by_date, reverse=True)
    chosen = date or (dates[0] if dates else None)
    if date and date not in by_date:
        raise HTTPException(status_code=404, detail=f"no {window} Stage IV data for {date}")
    rows = [_rainfall_row(r, window) for r in by_date.get(chosen or "", [])]
    rows.sort(key=lambda r: (-(r["obs_mean_in"] if isinstance(r["obs_mean_in"], (int, float)) else -1),
                             str(r["municipio"])))
    manifestations = {m.manifestation_id: m for m in store.load_manifestations(DATA_DIR)}
    files = []
    for man_id in dict.fromkeys(r["manifestation_id"] for r in rows):
        man = manifestations.get(man_id)
        if man is not None:
            files.append({
                "manifestation_id": man_id,
                "source_record_id": man.source_record_id,
                "source_url": man.source_url,
                "byte_sha256": man.byte_sha256,
                "retrieved_at": _iso(man.retrieved_at_utc),
            })
    return JSONResponse({
        "window": window,
        "window_days": stage_iv_qpe.WINDOW_DAYS[window],
        "windows": list(stage_iv_qpe.WINDOW_DAYS),
        "data_date": chosen,
        "available_dates": dates,
        "thresholds": {
            "mean_in": stage_iv_qpe.HEAVY_RAIN_MEAN_IN,
            "cell_max_in": stage_iv_qpe.HEAVY_RAIN_CELL_MAX_IN,
            "applies_to": "1day",
        },
        "files": files,
        "total": len(rows),
        "items": rows,
    })


def _load_script(script: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {script.name}")
    module = importlib.util.module_from_spec(spec)
    # Registered first: dataclasses resolve string annotations through sys.modules.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _run_script(script: Path, argv: list[str]) -> dict[str, Any]:
    """Run ``script``'s ``main`` in-process with its own argv; capture its output."""
    output, errors = io.StringIO(), io.StringIO()
    saved_argv = sys.argv
    code: int
    try:
        sys.argv = [str(script), *argv]
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            module = _load_script(script, f"aguayluz_hydromet_{script.stem}")
            try:
                code = int(module.main() or 0)
            except SystemExit as exc:  # argparse exits on bad arguments
                code = int(exc.code or 0) if isinstance(exc.code, int) else 1
    except Exception as exc:  # noqa: BLE001 - runs ingest code; report, don't crash the API
        errors.write(f"{type(exc).__name__}: {exc}")
        code = 1
    finally:
        sys.argv = saved_argv
    return {
        "script": f"scripts/{script.name}",
        "return_code": code,
        "stdout_tail": output.getvalue()[-1500:],
        "stderr_tail": errors.getvalue()[-1500:],
    }


@router.post("/hydromet/refresh/{source_id}", dependencies=[Depends(legacy._require_key)])
def hydromet_refresh(source_id: str) -> JSONResponse:
    """Re-run one source's ingest now, then rebuild alerts (single-flight)."""
    source = store.registry_source(source_id, _registry())
    if source is None or not source.get("refresh_script"):
        raise HTTPException(status_code=404, detail=f"unknown hydromet source {source_id!r}")
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="a hydromet refresh is already running")
    started = _now()
    _refresh_state.update(running=True, source_id=source_id, started_at=_iso(started), finished_at=None)
    try:
        steps = [_run_script(SCRIPTS / Path(source["refresh_script"]).name,
                             ["--data-dir", str(DATA_DIR)])]
        if steps[0]["return_code"] == 0:
            steps.append(_run_script(SCRIPTS / "build_alerts.py",
                                     ["--hydromet-dir", str(DATA_DIR)]))
            if steps[-1]["return_code"] == 0:
                steps.append(_run_script(SCRIPTS / "build_alert_system.py", []))
        ok = all(step["return_code"] == 0 for step in steps)
        result = {
            "ok": ok,
            "source_id": source_id,
            "started_at": _iso(started),
            "finished_at": _iso(_now()),
            "steps": steps,
            "receipt": store.load_receipts(DATA_DIR)["sources"].get(source_id),
        }
        _refresh_state.update(last_result=result, finished_at=result["finished_at"])
    finally:
        _refresh_state["running"] = False
        _refresh_lock.release()
    return JSONResponse(result, status_code=200 if ok else 502)


@router.get("/hydromet/refresh/status")
def hydromet_refresh_status() -> JSONResponse:
    return JSONResponse(dict(_refresh_state))
