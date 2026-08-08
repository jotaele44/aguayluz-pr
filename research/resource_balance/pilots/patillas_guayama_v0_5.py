"""Design-only Patillas T1 source-coverage and admission validator.

This module does not execute a real water balance or activate runtime surfaces.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_METRICS = {
    "upstream_inflow_rate",
    "reservoir_stage_start",
    "reservoir_stage_end",
    "gate_or_canal_release_rate",
    "direct_treatment_withdrawal_rate",
    "downstream_terminal_flow_rate",
    "area_weighted_precipitation_volume",
    "evaporation_volume",
    "documented_operational_loss_volume",
}
RATE_METRICS = {
    "upstream_inflow_rate",
    "gate_or_canal_release_rate",
    "direct_treatment_withdrawal_rate",
    "downstream_terminal_flow_rate",
}
STAGE_METRICS = {"reservoir_stage_start", "reservoir_stage_end"}
VOLUME_METRICS = {
    "area_weighted_precipitation_volume",
    "evaporation_volume",
    "documented_operational_loss_volume",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_scenarios(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    base = payload["base_complete_slice"]
    output: list[dict[str, Any]] = []
    for definition in payload["scenarios"]:
        scenario = copy.deepcopy(base)
        scenario["scenario_id"] = definition["scenario_id"]
        if metric := definition.get("remove_metric"):
            scenario["observations"] = [
                row for row in scenario["observations"] if row["metric"] != metric
            ]
        if mutation := definition.get("mutate"):
            row = next(x for x in scenario["observations"] if x["metric"] == mutation["metric"])
            row[mutation["field"]] = mutation["value"]
        if deletion := definition.get("delete_field"):
            row = next(x for x in scenario["observations"] if x["metric"] == deletion["metric"])
            row.pop(deletion["field"], None)
        output.append(scenario)
    return output


def admit_slice(scenario: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    observations = scenario.get("observations", [])
    by_metric: dict[str, dict[str, Any]] = {}
    for row in observations:
        metric = row.get("metric")
        if metric in by_metric:
            errors.append(f"duplicate_metric:{metric}")
        elif metric:
            by_metric[metric] = row

    for metric in sorted(REQUIRED_METRICS - set(by_metric)):
        errors.append(f"missing:{metric}")

    start = scenario.get("interval_start")
    end = scenario.get("interval_end")
    if not start or not end:
        errors.append("missing_slice_interval")
    else:
        duration = (parse_time(end) - parse_time(start)).total_seconds() / 60
        if duration != policy["slice_cadence_minutes"]:
            errors.append("invalid_slice_cadence")

    if scenario.get("topology_state_id") != policy["required_topology_state_id"]:
        errors.append("scenario_topology_mismatch")

    for metric, row in by_metric.items():
        if metric not in REQUIRED_METRICS:
            errors.append(f"unknown_metric:{metric}")
            continue
        if row.get("evidence_tier") != policy["required_evidence_tier"]:
            errors.append(f"evidence_tier:{metric}")
        if policy["require_provisional_false"] and row.get("provisional") is not False:
            errors.append(f"provisional:{metric}")
        if row.get("revision_status") != policy["required_revision_status"]:
            errors.append(f"revision:{metric}")
        if row.get("calibration_state") != policy["required_calibration_state"]:
            errors.append(f"calibration:{metric}")
        if row.get("topology_state_id") != policy["required_topology_state_id"]:
            errors.append(f"topology:{metric}")
        if policy["require_numeric_uncertainty"]:
            uncertainty = row.get("uncertainty_abs")
            if not isinstance(uncertainty, (int, float)) or uncertainty < 0:
                errors.append(f"uncertainty:{metric}")
        if policy["require_uncertainty_source"] and not row.get("uncertainty_source"):
            errors.append(f"uncertainty_source:{metric}")
        source_hash = str(row.get("source_sha256", ""))
        if policy["require_source_sha256"] and len(source_hash) != 64:
            errors.append(f"source_sha256:{metric}")
        if row.get("source_classification") != policy["require_source_classification"]:
            errors.append(f"source_classification:{metric}")

        if (
            metric in RATE_METRICS | VOLUME_METRICS
            and (row.get("interval_start") != start or row.get("interval_end") != end)
        ):
            errors.append(f"interval_alignment:{metric}")
        if metric in RATE_METRICS and row.get("unit") not in {"m3/s", "ft3/s"}:
            errors.append(f"unit:{metric}")
        if metric in VOLUME_METRICS and row.get("unit") != "m3":
            errors.append(f"unit:{metric}")
        if metric in STAGE_METRICS:
            if row.get("unit") != "m" or row.get("datum") != policy["require_stage_datum"]:
                errors.append(f"stage_reference:{metric}")
            boundary = start if metric.endswith("start") else end
            observed_at = row.get("observed_at")
            if not observed_at or not boundary:
                errors.append(f"stage_time:{metric}")
            else:
                skew = abs((parse_time(observed_at) - parse_time(boundary)).total_seconds()) / 60
                if skew > policy["stage_boundary_max_skew_minutes"]:
                    errors.append(f"stage_time:{metric}")

    return {
        "schema_version": "aguayluz.patillas-t1-admission-result/v0.5",
        "scenario_id": scenario.get("scenario_id"),
        "status": "admitted" if not errors else "rejected",
        "errors": sorted(set(errors)),
        "real_balance_executed": False,
        "root_cause_claim": None,
    }


def real_window_readiness(root: Path) -> dict[str, Any]:
    matrix = load_json(root / "source_coverage_matrix.json")
    blockers = [
        row["metric"]
        for row in matrix["inputs"]
        if row["admission_status"] != "admitted"
    ]
    return {
        "schema_version": "aguayluz.patillas-real-window-readiness/v0.5",
        "status": "blocked" if blockers else "eligible_for_separate_ballot",
        "blocking_metrics": blockers,
        "public_osint_status": matrix["public_osint_status"],
        "operator_requests_sent": matrix["operator_requests_sent"],
        "real_balance_executed": False,
        "root_cause_claim": None,
    }
