"""Design-only synchronized admission and stage-storage proof for Lago Patillas.

No provider polling, runtime persistence, API, GUI, export, alert, notification,
scheduler, migration, deprecation, or causal promotion is implemented here.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.resource_balance.core import (
    BalanceBoundary,
    BalanceWindow,
    ResourceObservation,
    compute_balance,
)

PILOT_ID = "patillas-guayama-synchronized-admission-v0.3"
PINNED_MAIN_SHA = "17c843595b5cdfbcef4e5f7b1ac6c662092e335d"
PINNED_PARENT_HEAD = "40fc362d7cb11cdabe3cde04733b41ceac97eb77"
CANONICAL_VOLUME_UNIT = "m3"
TOPOLOGY_STATE_ID = "topology:patillas-guayama:20260804:v0.2"
REQUIRED_METRICS = (
    "upstream_inflow_rate",
    "reservoir_stage_start",
    "reservoir_stage_end",
    "gate_or_canal_release_rate",
    "direct_treatment_withdrawal_rate",
    "downstream_flow_rate",
    "precipitation_volume",
    "evaporation_volume",
    "reservoir_operational_loss_volume",
    "canal_operational_loss_volume",
)
RATE_METRICS = {
    "upstream_inflow_rate",
    "gate_or_canal_release_rate",
    "direct_treatment_withdrawal_rate",
    "downstream_flow_rate",
}
STAGE_METRICS = {"reservoir_stage_start", "reservoir_stage_end"}
VOLUME_METRICS = {
    "precipitation_volume",
    "evaporation_volume",
    "reservoir_operational_loss_volume",
    "canal_operational_loss_volume",
}
RATE_TO_M3_S = {"m3/s": 1.0, "ft3/s": 0.028316846592}


def canonical_json(value: Any) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{text}\n".encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_admission_scenarios(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    base = payload["base_complete_window"]
    scenarios: list[dict[str, Any]] = []
    for definition in payload["scenarios"]:
        scenario = json.loads(json.dumps(base))
        scenario["scenario_id"] = definition["scenario_id"]
        scenario.update(definition.get("set_scenario", {}))
        removed = set(definition.get("remove_metrics", []))
        if removed:
            scenario["observations"] = [
                row for row in scenario["observations"] if row["metric"] not in removed
            ]
        if "keep_first_observations" in definition:
            count = int(definition["keep_first_observations"])
            scenario["observations"] = scenario["observations"][:count]
        mutation = definition.get("set_observation")
        if mutation:
            row = next(
                item for item in scenario["observations"] if item["metric"] == mutation["metric"]
            )
            row[mutation["field"]] = mutation["value"]
        duplicate = definition.get("duplicate_observation")
        if duplicate:
            row = next(
                item for item in scenario["observations"] if item["metric"] == duplicate["metric"]
            )
            copied = json.loads(json.dumps(row))
            copied["value"] = float(copied["value"]) + float(duplicate["value_delta"])
            scenario["observations"].append(copied)
        scenarios.append(scenario)
    return scenarios


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def valid_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdefABCDEF" for char in text)


def verify_receipt_payload(receipt: Mapping[str, Any]) -> bool:
    expected = receipt.get("receipt_payload_sha256")
    payload = {key: value for key, value in receipt.items() if key != "receipt_payload_sha256"}
    return valid_sha256(expected) and digest(payload) == expected


def validate_stage_storage_model(model: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = {
        "datum": "PRVD02",
        "stage_unit": "m",
        "storage_unit": CANONICAL_VOLUME_UNIT,
        "extrapolation_policy": "prohibited",
    }
    for field, value in expected.items():
        if model.get(field) != value:
            errors.append(f"invalid_{field}")
    if model.get("interpolation_policy") not in {
        "piecewise_linear_between_published_points",
        "prohibited_until_full_table_materialized",
    }:
        errors.append("unsupported_interpolation_policy")

    status = model.get("status")
    if status == "authoritative_source_identified_not_materialized":
        errors.append("stage_storage_table_not_materialized")
        return sorted(set(errors))
    if status not in {"materialized_authoritative", "synthetic_test_only"}:
        errors.append("unsupported_stage_storage_status")

    points = model.get("points", [])
    if len(points) < 2:
        errors.append("stage_storage_requires_two_points")
        return sorted(set(errors))
    prior_stage: float | None = None
    prior_storage: float | None = None
    for index, point in enumerate(points):
        try:
            stage = float(point["stage_m_prvd02"])
            storage = float(point["storage_m3"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"invalid_stage_storage_point:{index}")
            continue
        if prior_stage is not None and stage <= prior_stage:
            errors.append("stage_points_not_strictly_increasing")
        if prior_storage is not None and storage <= prior_storage:
            errors.append("storage_points_not_strictly_increasing")
        prior_stage, prior_storage = stage, storage
    try:
        uncertainty = float(model.get("uncertainty_abs_m3", -1))
    except (TypeError, ValueError):
        uncertainty = -1
    if uncertainty < 0:
        errors.append("invalid_stage_storage_uncertainty")
    return sorted(set(errors))


def stage_to_storage(
    stage_m_prvd02: float,
    model: Mapping[str, Any],
    *,
    observed_datum: str,
    source_hash: str,
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    errors = validate_stage_storage_model(model)
    if model.get("status") == "synthetic_test_only" and not allow_synthetic:
        errors.append("synthetic_stage_storage_model_forbidden")
    if errors:
        raise ValueError(";".join(sorted(set(errors))))
    if observed_datum != model["datum"]:
        raise ValueError("stage_datum_mismatch")
    if not valid_sha256(source_hash):
        raise ValueError("stage_source_hash_required")

    points = model["points"]
    stage = float(stage_m_prvd02)
    low = float(points[0]["stage_m_prvd02"])
    high = float(points[-1]["stage_m_prvd02"])
    if not low <= stage <= high:
        raise ValueError("stage_out_of_model_range")

    lower = points[0]
    upper = points[-1]
    for point in points:
        if float(point["stage_m_prvd02"]) == stage:
            lower = upper = point
            break
    else:
        for left, right in zip(points, points[1:], strict=True):
            if float(left["stage_m_prvd02"]) < stage < float(right["stage_m_prvd02"]):
                lower, upper = left, right
                break

    lower_stage = float(lower["stage_m_prvd02"])
    upper_stage = float(upper["stage_m_prvd02"])
    lower_storage = float(lower["storage_m3"])
    upper_storage = float(upper["storage_m3"])
    fraction = 0.0
    storage = lower_storage
    if upper_stage != lower_stage:
        fraction = (stage - lower_stage) / (upper_stage - lower_stage)
        storage = lower_storage + fraction * (upper_storage - lower_storage)
    storage = round(storage, 6)
    payload = {
        "schema_version": "aguayluz.stage-storage-transform-receipt/v0.3",
        "transform": "piecewise_linear_stage_to_storage",
        "model_id": model["model_id"],
        "model_version": model["model_version"],
        "model_hash": digest(model),
        "input": {"stage": stage, "unit": "m", "datum": observed_datum},
        "source_hash": source_hash,
        "bracket": {
            "lower_stage_m_prvd02": lower_stage,
            "lower_storage_m3": lower_storage,
            "upper_stage_m_prvd02": upper_stage,
            "upper_storage_m3": upper_storage,
            "fraction": fraction,
        },
        "output": {"storage": storage, "unit": CANONICAL_VOLUME_UNIT},
        "uncertainty_abs_m3": float(model["uncertainty_abs_m3"]),
        "interpolated": upper_stage != lower_stage,
        "rounding_decimals_m3": 6,
        "extrapolated": False,
        "claim_status": "derived",
    }
    return {
        "storage_m3": storage,
        "uncertainty_abs_m3": float(model["uncertainty_abs_m3"]),
        "receipt": {**payload, "receipt_id": f"AYL_STG_{digest(payload)[:20]}"},
    }


def rate_to_interval_volume(
    rate: float,
    rate_unit: str,
    start_at: str,
    end_at: str,
    *,
    uncertainty_abs_rate: float,
    source_hash: str,
) -> dict[str, Any]:
    if rate_unit not in RATE_TO_M3_S:
        raise ValueError("unsupported_rate_unit")
    if rate < 0 or uncertainty_abs_rate < 0:
        raise ValueError("negative_rate_or_uncertainty")
    if not valid_sha256(source_hash):
        raise ValueError("rate_source_hash_required")
    seconds = (parse_time(end_at) - parse_time(start_at)).total_seconds()
    if seconds <= 0:
        raise ValueError("invalid_interval")
    factor = RATE_TO_M3_S[rate_unit]
    volume = float(rate) * factor * seconds
    uncertainty = float(uncertainty_abs_rate) * factor * seconds
    payload = {
        "schema_version": "aguayluz.rate-volume-transform-receipt/v0.3",
        "transform": "constant_interval_rate_to_volume",
        "input": {
            "rate": float(rate),
            "unit": rate_unit,
            "interval_start": start_at,
            "interval_end": end_at,
        },
        "source_hash": source_hash,
        "duration_seconds": seconds,
        "conversion_factor_to_m3_s": factor,
        "output": {"volume": volume, "unit": CANONICAL_VOLUME_UNIT},
        "uncertainty_abs_m3": uncertainty,
        "claim_status": "derived",
    }
    return {
        "volume_m3": volume,
        "uncertainty_abs_m3": uncertainty,
        "receipt": {**payload, "receipt_id": f"AYL_RTV_{digest(payload)[:20]}"},
    }


def _observation_map(
    observations: list[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    by_metric: dict[str, Mapping[str, Any]] = {}
    errors: list[str] = []
    for item in observations:
        metric = str(item.get("metric", ""))
        if metric in by_metric:
            label = "duplicate" if canonical_json(by_metric[metric]) == canonical_json(item) else "contradictory_duplicate"
            errors.append(f"{label}:{metric}")
            continue
        by_metric[metric] = item
    return by_metric, errors


def admit_balance_window(
    scenario: Mapping[str, Any],
    policy: Mapping[str, Any],
    stage_model: Mapping[str, Any],
) -> dict[str, Any]:
    by_metric, errors = _observation_map(list(scenario.get("observations", [])))
    missing = sorted(metric for metric in REQUIRED_METRICS if metric not in by_metric)
    errors.extend(f"missing:{metric}" for metric in missing)

    start_at = str(scenario.get("window_start", ""))
    end_at = str(scenario.get("window_end", ""))
    try:
        start = parse_time(start_at)
        end = parse_time(end_at)
        evaluation = parse_time(str(scenario.get("evaluation_time", "")))
    except ValueError:
        errors.append("invalid_window_time")
        start = end = evaluation = datetime(1970, 1, 1, tzinfo=timezone.utc)
    if end <= start:
        errors.append("invalid_window_order")
    if scenario.get("topology_state_id") != policy.get("required_topology_state_id"):
        errors.append("topology_version_mismatch")
    if scenario.get("stage_storage_model_id") != stage_model.get("model_id"):
        errors.append("stage_storage_model_mismatch")
    if scenario.get("synthetic") is not True and stage_model.get("status") != "materialized_authoritative":
        errors.append("real_stage_storage_relation_not_materialized")
    errors.extend(validate_stage_storage_model(stage_model))
    if (evaluation - end).total_seconds() > float(policy.get("freshness_limit_hours", 48)) * 3600:
        errors.append("window_stale")

    allowed_skew = float(policy.get("max_time_skew_minutes", 60)) * 60
    for metric, item in by_metric.items():
        if metric not in REQUIRED_METRICS:
            errors.append(f"unknown_metric:{metric}")
            continue
        if scenario.get("synthetic") is not True and item.get("evidence_tier") != "T1":
            errors.append(f"non_T1:{metric}")
        checks = {
            "provisional": item.get("provisional") is False,
            "revision_not_current": item.get("revision_status") == "accepted_current",
            "sensor_not_verified": item.get("sensor_calibration_state") == "verified",
            "observation_topology_mismatch": item.get("topology_state_id") == policy.get("required_topology_state_id"),
            "source_hash": valid_sha256(item.get("source_hash")),
        }
        for label, passed in checks.items():
            if not passed:
                errors.append(f"{label}:{metric}")
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            errors.append(f"invalid_value:{metric}")
            continue
        if value < 0:
            errors.append(f"negative_value:{metric}")

        if metric in RATE_METRICS | VOLUME_METRICS:
            expected_units = policy.get("allowed_rate_units", []) if metric in RATE_METRICS else [CANONICAL_VOLUME_UNIT]
            if item.get("unit") not in expected_units:
                errors.append(f"unit:{metric}")
            if item.get("interval_start") != start_at or item.get("interval_end") != end_at:
                errors.append(f"interval_mismatch:{metric}")
        elif metric in STAGE_METRICS:
            if item.get("unit") != "m":
                errors.append(f"unit:{metric}")
            if item.get("datum") != stage_model.get("datum"):
                errors.append(f"datum_mismatch:{metric}")
            target = start if metric.endswith("start") else end
            try:
                observed = parse_time(str(item.get("observed_at", "")))
                if abs((observed - target).total_seconds()) > allowed_skew:
                    errors.append(f"time_skew:{metric}")
            except ValueError:
                errors.append(f"invalid_observed_at:{metric}")
            points = stage_model.get("points", [])
            if points:
                low = float(points[0]["stage_m_prvd02"])
                high = float(points[-1]["stage_m_prvd02"])
                if not low <= value <= high:
                    errors.append(f"stage_out_of_range:{metric}")

    return {
        "schema_version": "aguayluz.balance-window-admission-result/v0.3",
        "pilot_id": PILOT_ID,
        "window_id": scenario.get("window_id"),
        "status": "admitted" if not errors else "rejected",
        "errors": sorted(set(errors)),
        "missing_metrics": missing,
        "canonical_volume_unit": CANONICAL_VOLUME_UNIT,
        "root_cause_claim": None,
    }


def _resource_observation(
    identifier: str,
    quantity_kind: str,
    role: str,
    amount: float,
    uncertainty: float,
    window_end: str,
) -> ResourceObservation:
    return ResourceObservation(
        observation_id=identifier,
        asset_id="asset:patillas-guayama:synthetic",
        resource_domain="water",
        quantity_kind=quantity_kind,
        role=role,  # type: ignore[arg-type]
        amount=amount,
        unit=CANONICAL_VOLUME_UNIT,
        observed_at=window_end,
        source_ref="synthetic-regression:v0.3",
        source_hash="f" * 64,
        evidence_tier="T4",
        confidence=100,
        review_status="accepted",
        uncertainty_abs=uncertainty,
        eligible_for_balance=True,
    )


def _converted_rates(
    by_metric: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    converted: dict[str, dict[str, Any]] = {}
    for metric in RATE_METRICS:
        item = by_metric[metric]
        converted[metric] = rate_to_interval_volume(
            float(item["value"]),
            str(item["unit"]),
            str(item["interval_start"]),
            str(item["interval_end"]),
            uncertainty_abs_rate=float(item.get("uncertainty_abs", 0.0)),
            source_hash=str(item["source_hash"]),
        )
    return converted


def run_complete_synthetic_window(root: Path) -> dict[str, Any]:
    policy = load_json(root / "admission_policy.json")
    model = load_json(root / "synthetic_stage_storage_model.json")
    scenarios = load_admission_scenarios(root / "admission_fixtures.json")
    scenario = next(item for item in scenarios if item["scenario_id"] == "complete_window")
    admission = admit_balance_window(scenario, policy, model)
    if admission["status"] != "admitted":
        return {"admission": admission, "reservoir_balance": None, "canal_balance": None}
    by_metric, _ = _observation_map(scenario["observations"])
    start_storage = stage_to_storage(
        float(by_metric["reservoir_stage_start"]["value"]),
        model,
        observed_datum=str(by_metric["reservoir_stage_start"]["datum"]),
        source_hash=str(by_metric["reservoir_stage_start"]["source_hash"]),
        allow_synthetic=True,
    )
    end_storage = stage_to_storage(
        float(by_metric["reservoir_stage_end"]["value"]),
        model,
        observed_datum=str(by_metric["reservoir_stage_end"]["datum"]),
        source_hash=str(by_metric["reservoir_stage_end"]["source_hash"]),
        allow_synthetic=True,
    )
    storage_change = end_storage["storage_m3"] - start_storage["storage_m3"]
    storage_uncertainty = (
        start_storage["uncertainty_abs_m3"] ** 2 + end_storage["uncertainty_abs_m3"] ** 2
    ) ** 0.5
    converted = _converted_rates(by_metric)
    end_at = str(scenario["window_end"])
    window = BalanceWindow(
        str(scenario["window_id"]), str(scenario["window_start"]), end_at, "daily"
    )

    reservoir = compute_balance(
        BalanceBoundary(
            "boundary:patillas:reservoir:v0.3",
            "Synthetic Lago Patillas reservoir admission proof",
            "water",
            ("USGS_50092000", "USGS_50093045", "USGS_50093053"),
            (),
            TOPOLOGY_STATE_ID,
            "reservoir",
        ),
        window,
        [
            _resource_observation("obs:synthetic:upstream", "upstream_inflow", "inflow", converted["upstream_inflow_rate"]["volume_m3"], converted["upstream_inflow_rate"]["uncertainty_abs_m3"], end_at),
            _resource_observation("obs:synthetic:precipitation", "precipitation_volume", "inflow", float(by_metric["precipitation_volume"]["value"]), float(by_metric["precipitation_volume"].get("uncertainty_abs", 0.0)), end_at),
            _resource_observation("obs:synthetic:release", "gate_release", "outflow", converted["gate_or_canal_release_rate"]["volume_m3"], converted["gate_or_canal_release_rate"]["uncertainty_abs_m3"], end_at),
            _resource_observation("obs:synthetic:storage-change", "reservoir_storage_change", "storage_change", storage_change, storage_uncertainty, end_at),
            _resource_observation("obs:synthetic:evaporation", "evaporation_volume", "documented_loss", float(by_metric["evaporation_volume"]["value"]), float(by_metric["evaporation_volume"].get("uncertainty_abs", 0.0)), end_at),
            _resource_observation("obs:synthetic:reservoir-loss", "reservoir_operational_loss", "documented_loss", float(by_metric["reservoir_operational_loss_volume"]["value"]), float(by_metric["reservoir_operational_loss_volume"].get("uncertainty_abs", 0.0)), end_at),
        ],
    )
    canal = compute_balance(
        BalanceBoundary(
            "boundary:patillas-guayama:canal-treatment:v0.3",
            "Synthetic canal and treatment admission proof",
            "water",
            ("USGS_50093053", "USGS_50093075", "USGS_50093078", "USGS_50093083"),
            (),
            TOPOLOGY_STATE_ID,
            "treatment",
        ),
        window,
        [
            _resource_observation("obs:synthetic:canal-release", "canal_release", "inflow", converted["gate_or_canal_release_rate"]["volume_m3"], converted["gate_or_canal_release_rate"]["uncertainty_abs_m3"], end_at),
            _resource_observation("obs:synthetic:treatment", "direct_treatment_withdrawal", "outflow", converted["direct_treatment_withdrawal_rate"]["volume_m3"], converted["direct_treatment_withdrawal_rate"]["uncertainty_abs_m3"], end_at),
            _resource_observation("obs:synthetic:downstream", "downstream_flow", "outflow", converted["downstream_flow_rate"]["volume_m3"], converted["downstream_flow_rate"]["uncertainty_abs_m3"], end_at),
            _resource_observation("obs:synthetic:canal-loss", "canal_operational_loss", "documented_loss", float(by_metric["canal_operational_loss_volume"]["value"]), float(by_metric["canal_operational_loss_volume"].get("uncertainty_abs", 0.0)), end_at),
        ],
    )
    return {
        "admission": admission,
        "reservoir_balance": asdict(reservoir),
        "canal_balance": asdict(canal),
        "storage_change_m3": storage_change,
        "transform_receipts": {
            "stage_start": start_storage["receipt"],
            "stage_end": end_storage["receipt"],
            **{metric: value["receipt"] for metric, value in converted.items()},
        },
        "fact": "A synthetic complete window closes both nested balances.",
        "inference": "The proof does not establish a real Lago Patillas balance.",
        "root_cause_claim": None,
    }


def real_window_readiness(root: Path) -> dict[str, Any]:
    blockers = validate_stage_storage_model(load_json(root / "lago_patillas_stage_storage_model.json"))
    blockers.extend(
        [
            "missing_synchronized_T1_direct_treatment_withdrawal",
            "missing_synchronized_T1_downstream_terminal_flow",
            "missing_full_window_gate_or_canal_release",
            "missing_area_weighted_precipitation_volume",
            "missing_evaporation_volume",
            "missing_documented_operational_loss_volume",
        ]
    )
    return {
        "schema_version": "aguayluz.real-window-readiness/v0.3",
        "pilot_id": PILOT_ID,
        "status": "blocked",
        "blockers": sorted(set(blockers)),
        "real_balance_executed": False,
        "root_cause_claim": None,
    }
