"""Canonical FOOD_SYSTEM_RESILIENCE state and read-only API.

Scientific evidence is normalized here before it reaches any presentation layer.
The GUI consumes the deterministic view projection and never supplies scientific
coefficients or state back to this module.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
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


def _parse_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _hour_freshness(value: Any, max_age_hours: int = 1) -> str:
    observed = _parse_timestamp(value)
    if observed is None:
        return "UNKNOWN"
    age = datetime.now(timezone.utc) - observed
    if age < timedelta(0):
        return "UNKNOWN"
    return "FRESH" if age <= timedelta(hours=max_age_hours) else "STALE"


def _latest_metric(
    kind: str,
    metric: str,
    max_age_days: int,
    parameter_code: str | None = None,
) -> dict[str, Any]:
    path = legacy.READINGS_FILES.get(kind)
    rows = [
        r
        for r in _read_jsonl(path)
        if r.get("metric") == metric
        and (parameter_code is None or r.get("parameter_code") == parameter_code)
    ]
    if not rows:
        return {
            "available": False,
            "state": "UNKNOWN",
            "freshness": "UNKNOWN",
            "observed_date": None,
            "value": None,
            "unit": None,
            "source_ref": None,
            "site_no": None,
            "record_count": 0,
            "site_count": 0,
            "spatial_scope": "NO_OBSERVATION",
        }

    latest_day = max(str(r.get("observed_date") or "") for r in rows)
    current = [r for r in rows if str(r.get("observed_date") or "") == latest_day]
    site_ids = sorted({
        str(r.get("site_no"))
        for r in current
        if r.get("site_no") not in (None, "")
    })

    # A cross-site monitoring vector is evidence of availability/freshness, not an
    # islandwide scalar. Only expose a raw value when exactly one source record is
    # in the latest snapshot; otherwise retain the snapshot count and withhold an
    # arbitrary station value from the canonical sector signal.
    single = len(current) == 1
    observation = current[0] if single else None
    return {
        "available": True,
        "state": "UNKNOWN",
        "freshness": _freshness(latest_day, max_age_days),
        "observed_date": latest_day or None,
        "value": observation.get("value") if observation else None,
        "unit": observation.get("unit") if observation else None,
        "source_ref": observation.get("source_ref") if observation else None,
        "site_no": observation.get("site_no") if observation else None,
        "record_count": len(current),
        "site_count": len(site_ids),
        "spatial_scope": "SINGLE_SITE_OBSERVATION" if single else "MULTI_SITE_SNAPSHOT",
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
        "site_count": len({str(r.get("site_no")) for r in current if r.get("site_no") not in (None, "")}),
        "spatial_scope": "MUNICIPAL_WORST_CASE",
    }



def _grid_outage_signal() -> dict[str, Any]:
    receipt_path = legacy.DATA / "luma_live_receipt.json"
    events_path = legacy.DATA / "luma_live_incidents.jsonl"
    base = {
        "signal_id": "FOOD.P1.GRID_OUTAGE",
        "node_id": "POWER",
        "available": False,
        "state": "UNKNOWN",
        "freshness": "UNKNOWN",
        "observed_date": None,
        "value": None,
        "unit": "reported_outage_zone_events",
        "source_ref": None,
        "record_count": 0,
        "municipality_count": 0,
        "spatial_scope": "NO_VERIFIED_LIVE_RECEIPT",
        "evidence_state": "UNKNOWN",
        "observation_evidence_state": "UNKNOWN",
        "availability_state": "RECEIPT_MISSING",
        "state_semantics": (
            "MiLUMA town/zone warning only; never a certified grid-health or "
            "food-resilience state."
        ),
    }
    if not receipt_path.is_file():
        return base

    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {**base, "availability_state": "PROVENANCE_MISMATCH"}
    if not isinstance(receipt, dict):
        return {**base, "availability_state": "PROVENANCE_MISMATCH"}

    observed = receipt.get("retrieval_utc")
    freshness = _hour_freshness(observed, 1)
    source_ref = receipt.get("source_ref")
    common = {
        **base,
        "freshness": freshness,
        "observed_date": observed,
        "source_ref": source_ref,
        "requested_municipio_count": receipt.get("request_key_count"),
        "response_municipio_count": receipt.get("response_key_count"),
        "resolved_response_municipio_count": receipt.get("resolved_response_key_count"),
        "spatial_scope": "MUNICIPIO_TOWN_ZONE_FEED",
    }

    required = (
        receipt.get("schema_version") == "aguayluz.luma-live-receipt/v1"
        and receipt.get("status") == "PASS"
        and isinstance(receipt.get("output_sha256"), str)
        and isinstance(receipt.get("output_byte_count"), int)
        and isinstance(receipt.get("event_count"), int)
        and isinstance(source_ref, str)
        and source_ref
        and isinstance(receipt.get("source_byte_sha256"), str)
        and len(receipt["source_byte_sha256"]) == 64
    )
    if not required or not events_path.is_file():
        return {**common, "availability_state": "PROVENANCE_MISMATCH"}

    event_bytes = events_path.read_bytes()
    if (
        hashlib.sha256(event_bytes).hexdigest() != receipt["output_sha256"]
        or len(event_bytes) != receipt["output_byte_count"]
    ):
        return {**common, "availability_state": "PROVENANCE_MISMATCH"}

    events = _read_jsonl(events_path)
    if len(events) != receipt["event_count"]:
        return {**common, "availability_state": "PROVENANCE_MISMATCH"}
    if any(
        event.get("event_type") != "outage"
        or event.get("start_time") != observed
        or event.get("source_ref") != source_ref
        for event in events
    ):
        return {**common, "availability_state": "PROVENANCE_MISMATCH"}

    event_count = len(events)
    municipality_count = len(
        {str(event.get("municipality")) for event in events if event.get("municipality")}
    )
    complete_scope = (
        receipt.get("request_key_count") == 78
        and receipt.get("response_key_count") == 78
        and receipt.get("resolved_response_key_count") == 78
        and receipt.get("unresolved_response_keys") == []
    )

    if freshness != "FRESH":
        return {
            **common,
            "record_count": event_count,
            "municipality_count": municipality_count,
            "availability_state": "STALE" if freshness == "STALE" else "UNRESOLVED",
        }

    if event_count > 0:
        state = "WATCH"
        availability_state = "AVAILABLE" if complete_scope else "AVAILABLE_PARTIAL_COVERAGE"
    elif complete_scope:
        state = "NORMAL"
        availability_state = "AVAILABLE"
    else:
        state = "UNKNOWN"
        availability_state = "PARTIAL_COVERAGE"

    return {
        **common,
        "available": True,
        "state": state,
        "value": event_count,
        "record_count": event_count,
        "municipality_count": municipality_count,
        "availability_state": availability_state,
        "evidence_state": "COMPUTED",
        "observation_evidence_state": "FACT",
        "coverage_complete": complete_scope,
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
        "record_count": len(current),
        "spatial_scope": "EVENT_SET",
    }


def phase1_signals() -> list[dict[str, Any]]:
    contract = load_food_resilience_contract()
    live: dict[str, dict[str, Any]] = {
        "FOOD.P1.DROUGHT_CLASS": _drought_signal(),
        "FOOD.P1.RAINFALL_30D": {
            "signal_id": "FOOD.P1.RAINFALL_30D", "node_id": "WEATHER",
            **_latest_metric(
                "precipitation", "precipitation_pct_normal", 40, parameter_code="30d"
            ), "evidence_state": "FACT"
        },
        "FOOD.P1.RAINFALL_90D": {
            "signal_id": "FOOD.P1.RAINFALL_90D", "node_id": "WEATHER",
            **_latest_metric(
                "precipitation", "precipitation_pct_normal", 100, parameter_code="90d"
            ), "evidence_state": "FACT"
        },
        "FOOD.P1.STREAMFLOW": {
            "signal_id": "FOOD.P1.STREAMFLOW", "node_id": "SURFACE_WATER",
            **_latest_metric("reservoir", "streamflow", 3), "evidence_state": "FACT"
        },
        "FOOD.P1.GROUNDWATER": {
            "signal_id": "FOOD.P1.GROUNDWATER", "node_id": "GROUNDWATER",
            **_latest_metric("groundwater", "groundwater_level", 10), "evidence_state": "FACT"
        },
        "FOOD.P1.RESERVOIRS": {
            "signal_id": "FOOD.P1.RESERVOIRS", "node_id": "RESERVOIRS",
            **_latest_metric("reservoir", "reservoir_elevation", 3), "evidence_state": "FACT"
        },
        "FOOD.P1.TROPICAL_CYCLONE": _nhc_signal(),
        "FOOD.P1.GRID_OUTAGE": _grid_outage_signal(),
    }
    output: list[dict[str, Any]] = []
    for registry in contract["phase1_signals"]:
        signal_id = registry["signal_id"]
        if signal_id in live:
            item = {**registry, **live[signal_id]}
            if item.get("freshness") == "STALE":
                item["state"] = "UNKNOWN"
                item["availability_state"] = "STALE"
            elif not item.get("availability_state"):
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
    warning_state = _overall_state(signals)
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
        "overall_state": "UNKNOWN",
        "phase1_warning_state": warning_state,
        "state_semantics": "Phase 1 warning envelope; not a certified food-resilience score.",
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
            "warning_state": state["phase1_warning_state"],
            "state_semantics": state["state_semantics"],
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
