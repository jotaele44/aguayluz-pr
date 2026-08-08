"""Shared contracts for offline failure-localization operational adapters."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .contracts import digest, parse_timestamp

INPUT_SCHEMA = "aguayluz.failure-operational-input/v0.1"
RECEIPT_SCHEMA = "aguayluz.failure-operational-adapter-receipt/v0.1"
RUN_SCHEMA = "aguayluz.failure-operational-adapter-run/v0.1"
BUNDLE_SCHEMA = "aguayluz.failure-operational-bundle/v0.1"

INPUT_KINDS = {
    "asset_identity",
    "hydraulic_topology",
    "pressure_zone_membership",
    "flow",
    "pressure",
    "tank_level",
    "pump_state",
    "valve_state",
    "power",
    "production",
    "work_order",
    "outage",
    "restoration",
    "field_result",
}
GRAPH_KINDS = {
    "asset_identity",
    "hydraulic_topology",
    "pressure_zone_membership",
}
TELEMETRY_KINDS = {
    "flow",
    "pressure",
    "tank_level",
    "pump_state",
    "valve_state",
    "power",
    "production",
}
OBSERVATION_KINDS = TELEMETRY_KINDS | {
    "work_order",
    "outage",
    "restoration",
    "field_result",
}
EVIDENCE_TIERS = {"T1", "T2", "T3", "T4"}
FRESHNESS_STATES = {"current", "stale", "future", "unknown"}
QUALITY_STATES = {"valid", "suspect", "invalid"}
DISCLOSURE_STATES = {
    "public_exact",
    "public_approximate",
    "operator_restricted",
    "unresolved",
}
AUTHORITY_STATES = {
    "operator_authoritative",
    "regulator_authoritative",
    "public_authoritative",
    "operator_declared",
    "secondary",
    "inferred",
    "synthetic_fixture",
}
REVIEW_STATES = {"accepted", "needs_review", "rejected"}
AUTHORITATIVE_STATES = {
    "operator_authoritative",
    "regulator_authoritative",
    "public_authoritative",
}
FORBIDDEN_ACTIVE_KEYS = {
    "api_key",
    "authorization",
    "client_secret",
    "credential",
    "credentials",
    "mqtt_client",
    "password",
    "polling_enabled",
    "scada_client",
    "secret",
    "session_token",
    "token",
    "webhook_secret",
}
METRIC_BY_KIND = {
    "flow": "flow",
    "pressure": "pressure",
    "tank_level": "tank_level",
    "pump_state": "pump_state",
    "valve_state": "valve_state",
    "power": "power_state",
    "production": "production",
    "work_order": "work_order",
    "outage": "outage",
    "restoration": "restoration",
}
FIELD_METRICS = {
    "acoustic_confirmed_leak": "acoustic_confirmation",
    "field_confirmed_failure": "field_confirmation",
    "excavation_confirmed_break": "field_confirmation",
    "inspection_confirmed_failure": "field_confirmation",
}


class OperationalAdapterError(ValueError):
    """Raised for a fail-closed operational adapter contract violation."""


@dataclass(frozen=True)
class Admission:
    """Internal record admission result."""

    status: str
    reasons: tuple[str, ...]
    record: dict[str, Any] | None


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key).strip().lower()
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _required_text(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OperationalAdapterError(f"{key}_required")
    return value.strip()


def _payload_hash(payload: dict[str, Any]) -> str:
    return digest(payload)


def _is_current(record: dict[str, Any], as_of: datetime) -> bool:
    if record["freshness"] != "current":
        return False
    observed = parse_timestamp(record["observed_at"])
    if observed > as_of:
        return False
    max_age = record["payload"].get("max_age_seconds")
    if max_age is None:
        return True
    if not isinstance(max_age, int) or max_age <= 0:
        return False
    return (as_of - observed).total_seconds() <= max_age
