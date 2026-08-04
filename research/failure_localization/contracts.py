"""Frozen contracts and validation helpers for failure localization v0.1."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

SCHEMA_GRAPH = "aguayluz.failure-graph/v0.1"
SCHEMA_OBSERVATION = "aguayluz.failure-observation/v0.1"
SCHEMA_ASSESSMENT = "aguayluz.failure-assessment/v0.1"
LOCALIZATION_GRADES = {
    "L0": "cause class only",
    "L1": "service system or service area",
    "L2": "pressure zone",
    "L3": "specific facility or bounded segment candidate",
    "L4": "exact asset supported by authoritative asset evidence",
    "L5": "field-confirmed physical defect",
}
ASSET_TYPES = {
    "source", "intake", "treatment", "transmission", "tank", "pump", "valve",
    "pressure_zone", "distribution", "service_area", "sensor", "power_source",
}
HYDRAULIC_EDGE_TYPES = {"FEEDS", "TRANSFERS_TO", "SUPPLIES", "SERVES"}
EDGE_TYPES = HYDRAULIC_EDGE_TYPES | {"CONTROLS", "MONITORS", "POWERED_BY", "BACKUP_FOR"}
METRICS = {
    "flow", "pressure", "tank_level", "storage_change", "production", "demand",
    "source_availability", "pump_state", "valve_state", "power_state",
    "treatment_state", "outage", "restoration", "work_order",
    "failure_assertion", "field_confirmation", "acoustic_confirmation",
}
L4_ASSERTIONS = {
    "confirmed_asset_failure", "operator_confirmed_failure",
    "confirmed_configuration_error", "confirmed_main_break",
    "confirmed_pump_failure", "confirmed_valve_error", "confirmed_power_loss",
    "confirmed_tank_depletion", "confirmed_treatment_failure",
}
L5_ASSERTIONS = {
    "field_confirmed_failure", "acoustic_confirmed_leak",
    "excavation_confirmed_break", "inspection_confirmed_failure",
}
CONTROL_ASSET_TYPES = {"pump", "valve", "sensor", "power_source"}
ASSET_ID_RE = re.compile(r"^AYL_[A-Z0-9][A-Z0-9_.:-]{2,127}$")
EDGE_ID_RE = re.compile(r"^AYL_EDGE_[A-Z0-9][A-Z0-9_.:-]{2,127}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def stable_id(prefix: str, value: Any, length: int = 24) -> str:
    return f"{prefix}_{digest(value)[:length]}"


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp_timezone_required")
    return parsed.astimezone(timezone.utc)


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def state(value: Any) -> str:
    return str(value).strip().lower()


def unique(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value})


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    if graph.get("schema_version") not in {None, SCHEMA_GRAPH}:
        raise ValueError("unsupported_graph_schema")
    assets = [dict(item) for item in graph.get("assets", [])]
    edges = [dict(item) for item in graph.get("edges", [])]
    if not assets:
        raise ValueError("graph_assets_required")
    seen: set[str] = set()
    for asset in assets:
        asset_id = str(asset.get("asset_id", ""))
        if not ASSET_ID_RE.fullmatch(asset_id):
            raise ValueError(f"invalid_asset_id:{asset_id}")
        if asset_id in seen:
            raise ValueError(f"duplicate_asset_id:{asset_id}")
        seen.add(asset_id)
        if asset.get("asset_type") not in ASSET_TYPES:
            raise ValueError(f"invalid_asset_type:{asset_id}")
        asset.setdefault("name", asset_id)
        asset.setdefault("system_id", None)
        asset.setdefault("pressure_zone_id", None)
        asset.setdefault("service_area_id", None)
        asset.setdefault("disclosure", "unresolved")
        asset.setdefault("attributes", {})
        if asset["disclosure"] not in {
            "public_exact", "public_approximate", "operator_restricted", "unresolved"
        }:
            raise ValueError(f"invalid_asset_disclosure:{asset_id}")
    edge_seen: set[str] = set()
    for edge in edges:
        edge_id = str(edge.get("edge_id", ""))
        if not EDGE_ID_RE.fullmatch(edge_id):
            raise ValueError(f"invalid_edge_id:{edge_id}")
        if edge_id in edge_seen:
            raise ValueError(f"duplicate_edge_id:{edge_id}")
        edge_seen.add(edge_id)
        if edge.get("edge_type") not in EDGE_TYPES:
            raise ValueError(f"invalid_edge_type:{edge_id}")
        if edge.get("from_asset_id") not in seen or edge.get("to_asset_id") not in seen:
            raise ValueError(f"edge_endpoint_missing:{edge_id}")
        if edge["from_asset_id"] == edge["to_asset_id"]:
            raise ValueError(f"self_loop_forbidden:{edge_id}")
        edge.setdefault("topology_state", "unresolved")
        edge.setdefault("attributes", {})
        if edge["topology_state"] not in {
            "operator_declared", "public_authoritative", "inferred", "unresolved"
        }:
            raise ValueError(f"invalid_topology_state:{edge_id}")
    return {
        "assets": sorted(assets, key=lambda item: item["asset_id"]),
        "edges": sorted(edges, key=lambda item: item["edge_id"]),
    }


def validate_observation(
    observation: dict[str, Any], graph: dict[str, Any], default_max_age_seconds: int
) -> dict[str, Any]:
    row = dict(observation)
    if row.get("schema_version") != SCHEMA_OBSERVATION:
        raise ValueError("unsupported_observation_schema")
    if not row.get("observation_id"):
        raise ValueError("observation_id_required")
    parse_timestamp(str(row.get("observed_at", "")))
    asset_id, edge_id = row.get("asset_id"), row.get("edge_id")
    if bool(asset_id) == bool(edge_id):
        raise ValueError("observation_requires_exactly_one_target")
    assets = {item["asset_id"] for item in graph["assets"]}
    edges = {item["edge_id"] for item in graph["edges"]}
    if asset_id and asset_id not in assets:
        raise ValueError(f"unknown_observation_asset:{asset_id}")
    if edge_id and edge_id not in edges:
        raise ValueError(f"unknown_observation_edge:{edge_id}")
    if row.get("metric") not in METRICS:
        raise ValueError("unsupported_observation_metric")
    if row.get("review_status") not in {"accepted", "needs_review", "rejected"}:
        raise ValueError("invalid_review_status")
    if row.get("quality") not in {"valid", "suspect", "invalid"}:
        raise ValueError("invalid_quality")
    if row.get("evidence_tier") not in {"T1", "T2", "T3", "T4"}:
        raise ValueError("invalid_evidence_tier")
    if not row.get("source_id") or not row.get("source_kind"):
        raise ValueError("observation_source_required")
    defaults = {
        "authoritative": False, "field_confirmed": False, "assertion": "measurement",
        "unit": None, "expected_value": None, "tolerance": None, "uncertainty": 0.0,
        "max_age_seconds": default_max_age_seconds, "related_asset_ids": [], "notes": None,
    }
    for key, value in defaults.items():
        row.setdefault(key, value)
    if not isinstance(row["max_age_seconds"], int) or row["max_age_seconds"] <= 0:
        raise ValueError("max_age_seconds_must_be_positive_integer")
    uncertainty = number(row["uncertainty"])
    if uncertainty is None or uncertainty < 0:
        raise ValueError("uncertainty_must_be_nonnegative_number")
    row["uncertainty"] = uncertainty
    row["related_asset_ids"] = unique(map(str, row["related_asset_ids"]))
    if any(item not in assets for item in row["related_asset_ids"]):
        raise ValueError("unknown_related_asset")
    return row
