"""Frozen Patillas–Guayama water-balance regression pilot.

Design-only. The module consumes committed canonical extracts and synthetic
regression fixtures. It never polls a provider, writes production data, exposes
an API/GUI/export, raises an alert, or promotes a residual to a root-cause claim.
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

PILOT_ID = "patillas-guayama-water-balance-v0.2"
PINNED_MAIN_SHA = "17c843595b5cdfbcef4e5f7b1ac6c662092e335d"
STATUS_EQUIVALENCE = {
    "balanced_within_tolerance": {"balanced", "within_uncertainty"},
    "unexplained_positive_residual": {"unaccounted_deficit"},
    "contradictory_negative_residual": {"unaccounted_surplus"},
    "incomplete": {"insufficient_data"},
}
REQUIRED_LEGACY_METRICS = (
    "canal_release",
    "treatment_withdrawal",
    "agricultural_turnout",
    "terminal_flow",
)


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_source_manifest(root: Path) -> list[str]:
    manifest = load_json(root / "source_manifest.json")
    errors: list[str] = []
    if manifest.get("pilot_id") != PILOT_ID:
        errors.append("pilot_id_mismatch")
    if manifest.get("pinned_main_sha") != PINNED_MAIN_SHA:
        errors.append("pinned_main_sha_mismatch")
    for entry in manifest.get("entries", []):
        path = root / entry["path"]
        if not path.is_file():
            errors.append(f"missing:{entry['path']}")
            continue
        raw = path.read_bytes()
        if len(raw) != entry["size_bytes"]:
            errors.append(f"size:{entry['path']}")
        if sha256_bytes(raw) != entry["sha256"]:
            errors.append(f"sha256:{entry['path']}")
    return errors


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_topology(topology: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    assets = {item["asset_id"] for item in topology.get("assets", [])}
    edges = topology.get("edges", [])
    edge_ids: set[str] = set()
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        edge_id = edge["edge_id"]
        if edge_id in edge_ids:
            errors.append(f"duplicate_edge:{edge_id}")
        edge_ids.add(edge_id)
        if edge["from_asset_id"] not in assets or edge["to_asset_id"] not in assets:
            errors.append(f"orphan_edge:{edge_id}")
        adjacency.setdefault(edge["from_asset_id"], []).append(edge["to_asset_id"])

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"cycle:{node}")
            return
        if node in visited:
            return
        visiting.add(node)
        for neighbor in adjacency.get(node, []):
            visit(neighbor)
        visiting.remove(node)
        visited.add(node)

    for asset in assets:
        visit(asset)

    boundaries = topology.get("boundaries", [])
    boundary_ids = {item["boundary_id"] for item in boundaries}
    roots = [item for item in boundaries if item.get("parent_boundary_id") is None]
    if len(roots) != 1:
        errors.append("boundary_root_count")
    for boundary in boundaries:
        parent = boundary.get("parent_boundary_id")
        upstream = boundary.get("upstream_boundary_id")
        if parent is not None and parent not in boundary_ids:
            errors.append(f"unknown_parent:{boundary['boundary_id']}")
        if upstream is not None and upstream not in boundary_ids:
            errors.append(f"unknown_upstream:{boundary['boundary_id']}")
        for asset_id in boundary.get("asset_ids", []):
            if asset_id not in assets:
                errors.append(f"unknown_boundary_asset:{boundary['boundary_id']}:{asset_id}")
    return sorted(set(errors))


def frozen_observation_status(
    records: list[Mapping[str, Any]], max_skew_hours: float = 24.0
) -> dict[str, Any]:
    flow_records = [row for row in records if row.get("unit") == "ft3/s"]
    times = [parse_time(str(row["observed_at"])) for row in flow_records]
    skew = (max(times) - min(times)).total_seconds() / 3600 if len(times) > 1 else 0.0
    missing = [
        "storage_change",
        "synchronized_treatment_withdrawal",
        "terminal_flow",
        "validated_expected_loss_model",
    ]
    return {
        "status": (
            "insufficient_data"
            if missing
            else "unsynchronized"
            if skew > max_skew_hours
            else "eligible"
        ),
        "max_skew_hours": round(skew, 3),
        "allowed_skew_hours": max_skew_hours,
        "missing_required_quantities": missing,
        "root_cause_claim": None,
    }


def real_baseline_result(root: Path) -> dict[str, Any]:
    frozen = load_json(root / "frozen_observations.json")
    topology = load_json(root / "topology_state.json")
    boundary = BalanceBoundary(
        boundary_id="boundary:patillas-guayama:system",
        name="Patillas–Guayama frozen observed system",
        resource_domain="water",
        asset_ids=tuple(item["asset_id"] for item in topology["assets"]),
        edge_ids=tuple(item["edge_id"] for item in topology["edges"]),
        topology_state_id=topology["topology_state_id"],
        boundary_kind="system",
    )
    window = BalanceWindow(
        "window:patillas-guayama:frozen-202607",
        frozen["window_start"],
        frozen["window_end"],
        "frozen_multi-day",
    )
    observations = [
        ResourceObservation(
            observation_id=row["observation_id"],
            asset_id=row["asset_id"],
            resource_domain="water",
            quantity_kind=row["metric"],
            role="context",
            amount=float(row["value"]),
            unit=row["unit"],
            observed_at=row["observed_at"],
            source_ref=row["source_ref"],
            source_hash=row["source_hash"],
            evidence_tier=row["evidence_tier"],
            confidence=row["confidence"],
            review_status=row["review_status"],
            uncertainty_abs=float(row.get("uncertainty_abs", 0.0)),
            eligible_for_balance=False,
        )
        for row in frozen["observations"]
    ]
    result = compute_balance(boundary, window, observations)
    return {
        "balance_result": asdict(result),
        "eligibility": frozen_observation_status(frozen["observations"]),
        "topology_errors": validate_topology(topology),
        "fact": "The frozen baseline contains real provisional observations.",
        "inference": "No complete synchronized volumetric balance is supportable.",
    }


def legacy_laguna_balance(
    values: Mapping[str, Any], tolerance_fraction: float = 0.15
) -> dict[str, Any]:
    missing = sorted(metric for metric in REQUIRED_LEGACY_METRICS if metric not in values)
    if missing:
        return {
            "status": "incomplete",
            "missing_metrics": missing,
            "residual": None,
            "root_cause_claim": None,
        }
    units = {
        str(values[metric].get("unit"))
        for metric in (*REQUIRED_LEGACY_METRICS, "known_leak_flow")
        if metric in values
    }
    if units != {"ft3/s"}:
        return {
            "status": "mixed_or_unsupported_units",
            "units": sorted(units),
            "residual": None,
            "root_cause_claim": None,
        }
    release = float(values["canal_release"]["value"])
    treatment = float(values["treatment_withdrawal"]["value"])
    agriculture = float(values["agricultural_turnout"]["value"])
    terminal = float(values["terminal_flow"]["value"])
    leak = float(values.get("known_leak_flow", {}).get("value", 0.0))
    residual = release - treatment - agriculture - terminal - leak
    tolerance = abs(release) * tolerance_fraction
    if release <= 0:
        status = "invalid_nonpositive_release"
    elif residual < -tolerance:
        status = "contradictory_negative_residual"
    elif residual > tolerance:
        status = "unexplained_positive_residual"
    else:
        status = "balanced_within_tolerance"
    return {
        "status": status,
        "residual": residual,
        "tolerance": tolerance,
        "unit": "ft3/s",
        "root_cause_claim": None,
        "interpretation": "Accounting discrepancy only; leakage is not automatically inferred.",
    }


def shared_balance_from_legacy(
    values: Mapping[str, Any], scenario_id: str, tolerance_fraction: float = 0.15
) -> dict[str, Any]:
    missing = sorted(metric for metric in REQUIRED_LEGACY_METRICS if metric not in values)
    if missing:
        empty = compute_balance(
            BalanceBoundary(
                f"boundary:{scenario_id}",
                scenario_id,
                "water",
                ("asset:canal",),
                (),
                "topology:synthetic:v1",
            ),
            BalanceWindow(
                f"window:{scenario_id}",
                "2026-07-28T00:00:00-04:00",
                "2026-07-29T00:00:00-04:00",
                "daily",
            ),
            [],
        )
        return asdict(empty)

    release = float(values["canal_release"]["value"])
    uncertainty = abs(release) * tolerance_fraction
    role_by_metric = {
        "canal_release": "inflow",
        "treatment_withdrawal": "outflow",
        "agricultural_turnout": "outflow",
        "terminal_flow": "outflow",
        "known_leak_flow": "documented_loss",
    }
    observations = []
    for metric, role in role_by_metric.items():
        if metric not in values:
            continue
        item = values[metric]
        observations.append(
            ResourceObservation(
                observation_id=f"obs:{scenario_id}:{metric}",
                asset_id="asset:canal",
                resource_domain="water",
                quantity_kind=metric,
                role=role,
                amount=float(item["value"]),
                unit=str(item["unit"]),
                observed_at=str(
                    item.get("observed_at", "2026-07-28T06:30:00-04:00")
                ),
                source_ref=f"synthetic-regression:{scenario_id}",
                evidence_tier="T4",
                confidence=100,
                review_status="accepted",
                uncertainty_abs=uncertainty if metric == "canal_release" else 0.0,
                eligible_for_balance=True,
            )
        )
    result = compute_balance(
        BalanceBoundary(
            f"boundary:{scenario_id}",
            scenario_id,
            "water",
            ("asset:canal",),
            (),
            "topology:synthetic:v1",
        ),
        BalanceWindow(
            f"window:{scenario_id}",
            "2026-07-28T00:00:00-04:00",
            "2026-07-29T00:00:00-04:00",
            "daily",
        ),
        observations,
    )
    return asdict(result)


def compare_legacy_and_shared(scenario: Mapping[str, Any]) -> dict[str, Any]:
    values = scenario["values"]
    tolerance_fraction = float(scenario.get("tolerance_fraction", 0.15))
    legacy = legacy_laguna_balance(values, tolerance_fraction)
    if legacy["status"] == "mixed_or_unsupported_units":
        try:
            shared_balance_from_legacy(values, scenario["scenario_id"], tolerance_fraction)
        except ValueError as exc:
            return {
                "legacy": legacy,
                "shared_error": str(exc),
                "equivalent": "one canonical unit" in str(exc),
            }
        return {"legacy": legacy, "equivalent": False}
    shared = shared_balance_from_legacy(
        values, scenario["scenario_id"], tolerance_fraction
    )
    allowed = STATUS_EQUIVALENCE.get(legacy["status"], set())
    residual_equal = legacy.get("residual") is None or abs(
        float(legacy["residual"]) - float(shared["residual"])
    ) <= 1e-12
    return {
        "legacy": legacy,
        "shared": shared,
        "numeric_residual_equal": residual_equal,
        "semantic_status_equal": shared["status"] in allowed,
        "equivalent": residual_equal and shared["status"] in allowed,
        "differences": [
            "Legacy tolerance is release-fraction based; the shared core represents the same bound as an explicit uncertainty component.",
            "Legacy status names are domain-specific; shared status names are resource-neutral.",
            "Both paths leave root cause unresolved.",
        ],
    }


def apply_sensor_bias(
    values: Mapping[str, Any], metric: str, additive_correction: float
) -> dict[str, Any]:
    corrected = json.loads(json.dumps(values))
    corrected[metric]["value"] = float(corrected[metric]["value"]) + additive_correction
    corrected[metric]["bias_correction"] = {
        "amount": additive_correction,
        "claim_status": "inference",
        "requires_calibration_evidence": True,
    }
    return corrected
