"""Canonical FOOD_SYSTEM_RESILIENCE state and read-only API.

Scientific evidence is normalized here before it reaches any presentation layer.
The GUI consumes the deterministic view projection and never supplies scientific
coefficients or state back to this module.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from server.backend import main as legacy

router = APIRouter(prefix="/food-resilience", tags=["food-resilience"])

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "config" / "food_resilience.json"
STATE_ORDER = {"NORMAL": 0, "WATCH": 1, "ELEVATED": 2, "SEVERE": 3, "CRITICAL": 4}


def load_food_resilience_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _parse_day(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _freshness(observed: Any, max_age_days: int) -> str:
    day = _parse_day(observed)
    if day is None:
        return "UNKNOWN"
    age = (date.today() - day).days
    if age < 0:
        return "UNKNOWN"
    if age <= max_age_days:
        return "FRESH"
    if age <= max_age_days * 2:
        return "AGING"
    return "STALE"


def _latest_metric(kind: str, metric: str, max_age_days: int) -> dict[str, Any]:
    path = legacy.READINGS_FILES.get(kind)
    rows = [r for r in _read_jsonl(path) if r.get("metric") == metric]
    if not rows:
        return {
            "available": False,
            "state": "UNKNOWN",
            "freshness": "UNKNOWN",
            "observed_date": None,
            "value": None,
            "unit": None,
            "source_ref": None,
        }
    rows.sort(key=lambda r: str(r.get("observed_date") or ""))
    latest = rows[-1]
    return {
        "available": True,
        "state": "UNKNOWN",
        "freshness": _freshness(latest.get("observed_date"), max_age_days),
        "observed_date": latest.get("observed_date"),
        "value": latest.get("value"),
        "unit": latest.get("unit"),
        "source_ref": latest.get("source_ref"),
        "site_no": latest.get("site_no"),
    }


def _drought_signal() -> dict[str, Any]:
    path = legacy.READINGS_FILES.get("drought")
    rows = [r for r in _read_jsonl(path) if r.get("metric") == "drought_category"]
    if not rows:
        return {
            "signal_id": "FOOD.P1.DROUGHT_CLASS",
            "node_id": "DROUGHT",
            "available": False,
            "state": "UNKNOWN",
            "freshness": "UNKNOWN",
            "observed_date": None,
            "value": None,
            "unit": "category",
            "evidence_state": "UNKNOWN",
        }
    latest_day = max(str(r.get("observed_date") or "") for r in rows)
    current = [r for r in rows if str(r.get("observed_date") or "") == latest_day]
    numeric = [float(r["value"]) for r in current if isinstance(r.get("value"), (int, float))]
    worst = max(numeric) if numeric else None
    if worst is None:
        state = "UNKNOWN"
    elif worst < 0:
        state = "NORMAL"
    elif worst == 0:
        state = "WATCH"
    elif worst == 1:
        state = "ELEVATED"
    elif worst == 2:
        state = "SEVERE"
    else:
        state = "CRITICAL"
    return {
        "signal_id": "FOOD.P1.DROUGHT_CLASS",
        "node_id": "DROUGHT",
        "available": worst is not None,
        "state": state,
        "freshness": _freshness(latest_day, 10),
        "observed_date": latest_day or None,
        "value": worst,
        "unit": "USDM ordinal (-1 none; D0=0..D4=4)",
        "evidence_state": "COMPUTED",
        "source_ref": current[0].get("source_ref") if current else None,
        "record_count": len(current),
    }


def _nhc_signal() -> dict[str, Any]:
    rows = _read_jsonl(legacy.DATA / "service_events.jsonl")
    candidates = [
        row for row in rows
        if "NHC" in str(row.get("source_ref") or "").upper()
        or "NATIONAL HURRICANE CENTER" in str(row.get("source_ref") or "").upper()
    ]
    if not candidates:
        return {
            "signal_id": "FOOD.P1.TROPICAL_CYCLONE",
            "node_id": "HURRICANE",
            "available": False,
            "state": "UNKNOWN",
            "freshness": "UNKNOWN",
            "observed_date": None,
            "value": None,
            "unit": "event_count",
            "evidence_state": "UNKNOWN",
        }
    observed_fields = ("observed_date", "start_time", "effective_from", "reported_at")
    def observed(row: dict[str, Any]) -> str:
        for field in observed_fields:
            if row.get(field):
                return str(row[field])[:10]
        return ""
    latest_day = max(observed(row) for row in candidates)
    current = [row for row in candidates if observed(row) == latest_day]
    freshness = _freshness(latest_day, 2)
    state = "ELEVATED" if freshness in {"FRESH", "AGING"} and current else "UNKNOWN"
    return {
        "signal_id": "FOOD.P1.TROPICAL_CYCLONE",
        "node_id": "HURRICANE",
        "available": bool(current),
        "state": state,
        "freshness": freshness,
        "observed_date": latest_day or None,
        "value": len(current),
        "unit": "event_count",
        "evidence_state": "COMPUTED",
        "source_ref": current[0].get("source_ref") if current else None,
    }


def phase1_signals() -> list[dict[str, Any]]:
    contract = load_food_resilience_contract()
    live: dict[str, dict[str, Any]] = {
        "FOOD.P1.DROUGHT_CLASS": _drought_signal(),
        "FOOD.P1.RAINFALL_30D": {
            "signal_id": "FOOD.P1.RAINFALL_30D", "node_id": "WEATHER",
            **_latest_metric("precipitation", "precipitation_30d", 40), "evidence_state": "FACT"
        },
        "FOOD.P1.RAINFALL_90D": {
            "signal_id": "FOOD.P1.RAINFALL_90D", "node_id": "WEATHER",
            **_latest_metric("precipitation", "precipitation_90d", 100), "evidence_state": "FACT"
        },
        "FOOD.P1.STREAMFLOW": {
            "signal_id": "FOOD.P1.STREAMFLOW", "node_id": "SURFACE_WATER",
            **_latest_metric("reservoir", "streamflow", 3), "evidence_state": "FACT"
        },
        "FOOD.P1.GROUNDWATER": {
            "signal_id": "FOOD.P1.GROUNDWATER", "node_id": "GROUNDWATER",
            **_latest_metric("groundwater", "groundwater_depth", 10), "evidence_state": "FACT"
        },
        "FOOD.P1.RESERVOIRS": {
            "signal_id": "FOOD.P1.RESERVOIRS", "node_id": "RESERVOIRS",
            **_latest_metric("reservoir", "reservoir_elevation", 3), "evidence_state": "FACT"
        },
        "FOOD.P1.TROPICAL_CYCLONE": _nhc_signal(),
    }
    output: list[dict[str, Any]] = []
    for registry in contract["phase1_signals"]:
        signal_id = registry["signal_id"]
        if signal_id in live:
            item = {**registry, **live[signal_id]}
            if item.get("freshness") == "STALE":
                item["state"] = "UNKNOWN"
                item["availability_state"] = "STALE"
            else:
                item["availability_state"] = "AVAILABLE" if item.get("available") else "SOURCE_MISSING"
        else:
            item = {
                **registry,
                "available": False,
                "state": "UNKNOWN",
                "freshness": "UNKNOWN",
                "observed_date": None,
                "value": None,
                "unit": None,
                "evidence_state": "UNRESOLVED" if registry["state"] == "UNRESOLVED" else "UNKNOWN",
                "availability_state": "UNRESOLVED" if registry["state"] == "UNRESOLVED" else "MODEL_UNAVAILABLE",
            }
        output.append(item)
    return output


def _overall_state(signals: list[dict[str, Any]]) -> str:
    scored = [s["state"] for s in signals if s.get("state") in STATE_ORDER]
    return max(scored, key=STATE_ORDER.get) if scored else "UNKNOWN"


def canonical_food_resilience_state() -> dict[str, Any]:
    contract = load_food_resilience_contract()
    signals = phase1_signals()
    usable = [s for s in signals if s.get("available") and s.get("freshness") != "STALE"]
    completeness = round(len(usable) / len(signals), 3) if signals else 0.0
    water_states = [s["state"] for s in signals if s["node_id"] in {"DROUGHT", "SURFACE_WATER", "GROUNDWATER", "RESERVOIRS"} and s.get("state") in STATE_ORDER]
    ag_water = max(water_states, key=STATE_ORDER.get) if water_states else "UNKNOWN"
    overall = _overall_state(signals)
    confidence = "MODERATE" if completeness >= 0.5 else "LOW"
    now = datetime.now(timezone.utc).isoformat()
    unavailable_metric = {
        "value": None,
        "low": None,
        "high": None,
        "unit": "percent",
        "availability_state": "MODEL_UNAVAILABLE",
        "evidence_state": "UNKNOWN",
        "reference_period": None,
    }
    return {
        "state_id": f"FOOD_STATE_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "vector_id": contract["vector_id"],
        "as_of": now,
        "activation_phase": 1,
        "overall_state": overall,
        "trend": "UNKNOWN",
        "components": {
            "AG_WATER": ag_water,
            "POWER": "UNKNOWN",
            "PORTS": "UNKNOWN",
            "ROADS": "UNKNOWN",
            "PRODUCTION": "UNKNOWN",
            "IMPORTS": "UNKNOWN",
            "FEED": "UNKNOWN",
            "COLD_CHAIN": "UNKNOWN",
            "PROCESSING": "UNKNOWN",
            "FISHERIES": "UNKNOWN",
        },
        "metrics": {
            "current_output_coverage": dict(unavailable_metric),
            "current_nutrition_coverage": dict(unavailable_metric),
            "dynamic_coverage": dict(unavailable_metric),
            "robust_coverage_p50": dict(unavailable_metric),
        },
        "phase1_signals": signals,
        "bindings": {"primary": None, "secondary": None},
        "uncertainty": {"enabled": False, "reason": "Phase 3 and Phase 4 model outputs remain locked."},
        "data_completeness": completeness,
        "confidence": confidence,
        "freshness": "FRESH" if any(s.get("freshness") == "FRESH" for s in usable) else "UNKNOWN",
        "baseline_id": "PR_FOOD_VECTOR_A_V0_1",
        "model_version": "food-resilience-v0.1",
        "scenario_set_id": None,
        "tracking_issue": contract["tracking_issue"],
        "phase_lock_review_date": contract["phase_lock_review_date"],
    }


def food_resilience_view() -> dict[str, Any]:
    state = canonical_food_resilience_state()
    baseline = load_food_resilience_contract()["phase2_baseline"]
    return {
        "view_id": f"FOOD_VIEW_{state['state_id']}",
        "vector_id": state["vector_id"],
        "generated_utc": state["as_of"],
        "projection_version": "food_gui_projection_v0.1",
        "summary": {
            "title": "Food System Resilience",
            "state": state["overall_state"],
            "trend": state["trend"],
            "phase": "PHASE_1_OBSERVABLE",
            "confidence": state["confidence"],
            "data_completeness": state["data_completeness"],
            "as_of": state["as_of"],
        },
        "components": [{"id": key, "state": value} for key, value in state["components"].items()],
        "signals": state["phase1_signals"],
        "baseline": baseline,
        "scenarios": [
            {"id": "DYNAMIC_COVERAGE", "required_phase": 3, "availability": "MODEL_UNAVAILABLE", "tracking_issue": state["tracking_issue"]},
            {"id": "ROBUST_COVERAGE", "required_phase": 4, "availability": "MODEL_UNAVAILABLE", "tracking_issue": state["tracking_issue"]},
        ],
        "bindings": [],
        "uncertainty": state["uncertainty"],
        "methodology": {
            "invariant": "Scientific model -> canonical state -> deterministic GUI projection.",
            "forbidden": "GUI -> scientific truth",
        },
    }


@router.get("/state")
def food_resilience_state() -> dict[str, Any]:
    return canonical_food_resilience_state()


@router.get("/view")
def food_resilience_gui_view() -> dict[str, Any]:
    return food_resilience_view()


@router.get("/dependencies")
def food_resilience_dependencies() -> dict[str, Any]:
    contract = load_food_resilience_contract()
    return {"nodes": contract["nodes"], "edges": contract["edges"], "count_nodes": len(contract["nodes"]), "count_edges": len(contract["edges"])}


@router.get("/phase1/signals")
def food_resilience_phase1_signals() -> dict[str, Any]:
    items = phase1_signals()
    return {"total": len(items), "items": items}


@router.get("/baseline")
def food_resilience_baseline() -> dict[str, Any]:
    return load_food_resilience_contract()["phase2_baseline"]


@router.get("/scenarios")
def food_resilience_scenarios() -> dict[str, Any]:
    contract = load_food_resilience_contract()
    return {
        "phase3": contract["phase3_adapter"],
        "phase4": contract["phase4_adapter"],
        "tracking_issue": contract["tracking_issue"],
        "review_date": contract["phase_lock_review_date"],
    }
