"""Deterministic contradiction and negative-control replays."""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from server.backend.water_disruption import WaterIncidentService

from .model import build_observation, stable_token


def _synthetic(
    *,
    location_id: str,
    metric: str,
    value: float,
    unit: str,
    observed_at: datetime,
    window: str,
) -> dict[str, Any]:
    return build_observation(
        source_id="SYNTHETIC_REPLAY_ONLY",
        source_record_id=stable_token(location_id, metric, observed_at.isoformat(), value, unit),
        source_hash="0" * 64,
        provider="synthetic_replay",
        location_id=location_id,
        metric=metric,
        value=value,
        unit=unit,
        observed_at=observed_at,
        window_id=window,
        qa_status="accepted",
        method="deterministic negative-control replay",
        notes="Never ingested as live provider evidence.",
    )


def _scenario_summary(rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="laguna-replay-") as tmp:
        service = WaterIncidentService(Path(tmp))
        receipts = [
            service.intake(row, f"REPLAY:{row['observation_id']}") for row in rows
        ]
        summary = service.laguna_cartagena_summary(now=now)
    return {"receipts": receipts, "summary": summary}


def _balance_rows(
    now: datetime,
    window: str,
    offsets: list[int],
    units: list[str],
    values: list[float],
) -> list[dict[str, Any]]:
    metrics_sites = (
        ("canal_release", "50128905"),
        ("treatment_withdrawal", "50128905"),
        ("agricultural_turnout", "50128905"),
        ("terminal_flow", "50128940"),
    )
    rows = []
    for (metric, site), offset, unit, value in zip(
        metrics_sites,
        offsets,
        units,
        values,
        strict=True,
    ):
        row = _synthetic(
            location_id=site,
            metric="canal_release" if metric == "treatment_withdrawal" else metric,
            value=value,
            unit=unit,
            observed_at=now - timedelta(hours=offset),
            window=window,
        )
        row["metric"] = metric
        row["observation_id"] = (
            f"AYL_LC_OBS_{stable_token(window, metric, offset, unit, value)}"
        )
        rows.append(row)
    return rows


def run_replay_matrix(now: datetime) -> dict[str, Any]:
    stale = _synthetic(
        location_id="50129899",
        metric="lagoon_stage",
        value=1.0,
        unit="ft",
        observed_at=now - timedelta(days=10),
        window="REPLAY_STALE",
    )
    guil = build_observation(
        source_id="SYNTHETIC_REPLAY_ONLY",
        source_record_id="guil-groundwater",
        source_hash="0" * 64,
        provider="synthetic_replay",
        location_id="180046067053700",
        metric="groundwater_level",
        value=2.0,
        unit="ft",
        observed_at=now,
        window_id="REPLAY_GUIL",
        qa_status="accepted",
        method="deterministic negative-control replay",
        notes="Location ID is replaced with GUIL after schema construction.",
    )
    guil.update(
        {
            "location_id": "GUIL",
            "location_name": "Río Yahuecas",
            "direct_or_proxy": "proxy",
            "hydrologic_representativeness": "none",
        }
    )
    scenarios = {
        "stale_direct": [stale],
        "guil_substitution": [guil],
        "unsynchronized_balance": _balance_rows(
            now,
            "REPLAY_UNSYNC",
            [0, 1, 2, 30],
            ["ft3/s"] * 4,
            [100, 20, 20, 30],
        ),
        "mixed_unit_balance": _balance_rows(
            now,
            "REPLAY_MIXED",
            [0, 1, 2, 3],
            ["ft3/s", "MGD", "ft3/s", "ft3/s"],
            [100, 20, 20, 30],
        ),
        "negative_residual": _balance_rows(
            now,
            "REPLAY_NEGATIVE",
            [0, 1, 2, 3],
            ["ft3/s"] * 4,
            [10, 8, 5, 2],
        ),
        "positive_residual": _balance_rows(
            now,
            "REPLAY_POSITIVE",
            [0, 1, 2, 3],
            ["ft3/s"] * 4,
            [100, 10, 10, 10],
        ),
    }
    output: dict[str, Any] = {}
    for name, rows in scenarios.items():
        result = _scenario_summary(rows, now)
        summary = result["summary"]
        output[name] = {
            "eligible_flags": [
                receipt.get("current_condition_eligible")
                for receipt in result["receipts"]
            ],
            "eligibility_reasons": [
                receipt.get("eligibility_reasons", [])
                for receipt in result["receipts"]
            ],
            "synchronization_status": summary["synchronization"]["status"],
            "water_balance_status": summary["water_balance"]["status"],
            "root_cause_claim": summary["water_balance"].get("root_cause_claim"),
            "hypotheses": summary["hypotheses"],
            "contradictions": summary["contradictions"],
        }
    return output


def validate_replay_matrix(matrix: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if matrix["stale_direct"]["eligible_flags"] != [False]:
        failures.append("stale_direct_promoted")
    if "guil_not_lajas_groundwater_substitute" not in (
        matrix["guil_substitution"]["eligibility_reasons"][0]
    ):
        failures.append("guil_substitution_not_blocked")
    if matrix["unsynchronized_balance"]["water_balance_status"] != "not_computed":
        failures.append("unsynchronized_balance_computed")
    if matrix["mixed_unit_balance"]["water_balance_status"] != "not_computed":
        failures.append("mixed_unit_balance_computed")
    if matrix["negative_residual"]["water_balance_status"] != (
        "contradictory_negative_residual"
    ):
        failures.append("negative_residual_not_contradiction")
    if matrix["positive_residual"]["water_balance_status"] != (
        "unexplained_positive_residual"
    ):
        failures.append("positive_residual_not_candidate")
    if matrix["positive_residual"]["root_cause_claim"] is not None:
        failures.append("positive_residual_auto_promoted")
    return failures
