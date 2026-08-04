"""Design-only shared resource accounting core for AguaYLuz.

The module is deliberately outside runtime package and API discovery roots. It
proves the common water/electricity accounting contracts without activating
routes, exports, alerts, notifications, or data migration.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Sequence

ContractVersion = Literal["resource-balance/v0.1"]
ResourceDomain = Literal["water", "electricity", "wastewater", "fuel", "unknown"]
EvidenceTier = Literal["T1", "T2", "T3", "T4"]
ReviewStatus = Literal["accepted", "needs_review", "rejected", "blocked"]
ObservationRole = Literal[
    "inflow", "outflow", "generation", "consumption", "charge", "discharge",
    "storage_change", "documented_loss", "context",
]
BalanceStatus = Literal[
    "balanced", "within_uncertainty", "unaccounted_deficit",
    "unaccounted_surplus", "insufficient_data",
]
AttributionCause = Literal[
    "technical_loss", "meter_error", "time_alignment_error", "topology_error",
    "distributed_resource_gap", "unmetered_public_load", "hydrologic_model_gap",
    "operational_release", "evaporation_or_seepage", "treatment_process_loss",
    "transmission_or_distribution_loss", "unrecorded_withdrawal", "unresolved",
]


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:20]}"


@dataclass(frozen=True)
class ResourceAsset:
    resource_asset_id: str
    name: str
    resource_domain: ResourceDomain
    asset_kind: str
    source_ref: str
    evidence_tier: EvidenceTier
    confidence: int
    review_status: ReviewStatus
    legacy_asset_id: str | None = None
    operator: str | None = None
    municipality: str | None = None
    status: str = "unknown"
    compatibility_mode: Literal["native", "legacy_wrapper"] = "native"
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class ResourceFlowEdge:
    edge_id: str
    resource_domain: ResourceDomain
    from_asset_id: str
    to_asset_id: str
    relationship: str
    source_ref: str
    evidence_tier: EvidenceTier
    confidence: int
    review_status: ReviewStatus
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class ResourceObservation:
    observation_id: str
    asset_id: str
    resource_domain: ResourceDomain
    quantity_kind: str
    role: ObservationRole
    amount: float
    unit: str
    observed_at: str
    source_ref: str
    evidence_tier: EvidenceTier
    confidence: int
    review_status: ReviewStatus
    uncertainty_abs: float = 0.0
    eligible_for_balance: bool = False
    source_hash: str | None = None
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class StorageState:
    storage_state_id: str
    asset_id: str
    resource_domain: ResourceDomain
    amount: float
    unit: str
    observed_at: str
    source_ref: str
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class ConversionProcess:
    process_id: str
    asset_id: str
    resource_domain: ResourceDomain
    input_quantity_kind: str
    output_quantity_kind: str
    source_ref: str
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class BalanceBoundary:
    boundary_id: str
    name: str
    resource_domain: ResourceDomain
    asset_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    topology_state_id: str
    boundary_kind: str = "custom"
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class BalanceWindow:
    window_id: str
    start_at: str
    end_at: str
    cadence: str
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class ExpectedLossModel:
    loss_model_id: str
    boundary_id: str
    resource_domain: ResourceDomain
    amount: float
    unit: str
    uncertainty_abs: float
    model_kind: str
    model_version: str
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class UncertaintyEnvelope:
    uncertainty_envelope_id: str
    method: Literal["root_sum_square"]
    absolute_tolerance: float
    unit: str
    component_count: int
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class ResidualAttribution:
    attribution_id: str
    cause: AttributionCause
    claim_status: Literal["fact", "inference", "unresolved"]
    confidence: int
    notes: tuple[str, ...]
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class BalanceResult:
    balance_result_id: str
    boundary_id: str
    window_id: str
    topology_state_id: str
    resource_domain: ResourceDomain
    unit: str
    gross_input: float
    gross_output: float
    storage_change: float
    documented_loss: float
    expected_loss: float
    residual: float
    uncertainty_envelope: UncertaintyEnvelope
    status: BalanceStatus
    attribution: ResidualAttribution
    facts: tuple[str, ...]
    inferences: tuple[str, ...]
    excluded_observation_ids: tuple[str, ...] = field(default_factory=tuple)
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class TopologyState:
    topology_state_id: str
    resource_domain: ResourceDomain
    valid_from: str
    valid_until: str | None
    asset_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    source_ref: str
    contract_version: ContractVersion = "resource-balance/v0.1"


@dataclass(frozen=True)
class InvestigationCase:
    investigation_case_id: str
    balance_result_ids: tuple[str, ...]
    status: Literal["open", "closed", "blocked"]
    hypotheses: tuple[AttributionCause, ...]
    required_evidence: tuple[str, ...]
    contract_version: ContractVersion = "resource-balance/v0.1"


def resource_asset_from_utility_asset(asset: Any) -> ResourceAsset:
    """Wrap a legacy UtilityAsset without rewriting or deleting its source row."""
    raw_type = str(asset.asset_type)
    domain: ResourceDomain = {
        "water": "water", "wastewater": "wastewater", "power": "electricity",
        "fuel": "fuel",
    }.get(raw_type, "unknown")  # type: ignore[assignment]
    return ResourceAsset(
        resource_asset_id=f"legacy:{asset.asset_id}",
        legacy_asset_id=asset.asset_id,
        name=asset.asset_name,
        resource_domain=domain,
        asset_kind=asset.asset_subtype,
        operator=asset.operator,
        municipality=asset.municipality,
        status=asset.status,
        source_ref=asset.source_ref,
        evidence_tier=asset.evidence_tier,
        confidence=asset.confidence,
        review_status=asset.review_status,
        compatibility_mode="legacy_wrapper",
    )


def resource_observation_from_monitoring_reading(reading: Mapping[str, Any]) -> ResourceObservation:
    """Preserve legacy readings as context until direction, interval and uncertainty are known."""
    metric = str(reading.get("metric", "other"))
    domain: ResourceDomain = "electricity" if metric in {"generation", "reliability"} else "water"
    date = str(reading.get("observed_date") or reading.get("date") or "")
    return ResourceObservation(
        observation_id=f"legacy:{reading['reading_id']}",
        asset_id=f"legacy:{reading['asset_id']}",
        resource_domain=domain,
        quantity_kind=metric,
        role="context",
        amount=float(reading["value"]),
        unit=str(reading["unit"]),
        observed_at=f"{date}T00:00:00Z" if len(date) == 10 else date,
        source_ref=str(reading["source_ref"]),
        source_hash=reading.get("source_hash"),
        evidence_tier=reading["evidence_tier"],
        confidence=int(reading["confidence"]),
        review_status=reading["review_status"],
        uncertainty_abs=0.0,
        eligible_for_balance=False,
    )


def compute_balance(
    boundary: BalanceBoundary,
    window: BalanceWindow,
    observations: Sequence[ResourceObservation],
    expected_losses: Sequence[ExpectedLossModel] = (),
) -> BalanceResult:
    """Compute a deterministic, uncertainty-bounded balance for water or electricity."""
    eligible = [o for o in observations if o.eligible_for_balance and o.role != "context"]
    excluded = tuple(o.observation_id for o in observations if o not in eligible)
    base = {"boundary": boundary.boundary_id, "window": window.window_id}
    if not eligible:
        envelope = UncertaintyEnvelope(_stable_id("AYL_RBU", base), "root_sum_square", 0.0, "unknown", 0)
        attribution = ResidualAttribution(
            _stable_id("AYL_RBA", base), "unresolved", "unresolved", 0,
            ("No balance-eligible observations were supplied.",),
        )
        return BalanceResult(
            _stable_id("AYL_RBR", base), boundary.boundary_id, window.window_id,
            boundary.topology_state_id, boundary.resource_domain, "unknown", 0, 0, 0, 0, 0, 0,
            envelope, "insufficient_data", attribution, (), (), excluded,
        )

    units = {o.unit for o in eligible} | {m.unit for m in expected_losses}
    if len(units) != 1:
        raise ValueError(f"balance requires one canonical unit; received {sorted(units)}")
    domains = {o.resource_domain for o in eligible} | {m.resource_domain for m in expected_losses}
    if domains != {boundary.resource_domain}:
        raise ValueError("observations and loss models must match boundary resource domain")
    if any(m.boundary_id != boundary.boundary_id for m in expected_losses):
        raise ValueError("expected-loss model boundary mismatch")

    unit = next(iter(units))
    gross_input = sum(o.amount for o in eligible if o.role in {"inflow", "generation", "discharge"})
    gross_output = sum(o.amount for o in eligible if o.role in {"outflow", "consumption", "charge"})
    storage_change = sum(o.amount for o in eligible if o.role == "storage_change")
    documented_loss = sum(o.amount for o in eligible if o.role == "documented_loss")
    expected_loss = sum(m.amount for m in expected_losses)
    residual = gross_input - gross_output - storage_change - documented_loss - expected_loss
    components = [o.uncertainty_abs for o in eligible] + [m.uncertainty_abs for m in expected_losses]
    tolerance = math.sqrt(sum(value * value for value in components))
    envelope = UncertaintyEnvelope(
        _stable_id("AYL_RBU", {**base, "components": components, "unit": unit}),
        "root_sum_square", tolerance, unit, len(components),
    )
    if abs(residual) <= 1e-12:
        status: BalanceStatus = "balanced"
    elif abs(residual) <= tolerance:
        status = "within_uncertainty"
    elif residual > 0:
        status = "unaccounted_deficit"
    else:
        status = "unaccounted_surplus"

    attribution = ResidualAttribution(
        _stable_id("AYL_RBA", {**base, "residual": residual, "status": status}),
        "unresolved",
        "unresolved" if status in {"balanced", "within_uncertainty"} else "inference",
        0,
        (
            "The residual identifies an accounting discrepancy only.",
            "No theft, fraud, illegal diversion, unauthorized use, or exact failure location is inferred.",
        ),
    )
    facts = (
        f"gross_input={gross_input} {unit}", f"gross_output={gross_output} {unit}",
        f"storage_change={storage_change} {unit}", f"documented_loss={documented_loss} {unit}",
        f"expected_loss={expected_loss} {unit}", f"uncertainty_tolerance={tolerance} {unit}",
    )
    inferences = () if status in {"balanced", "within_uncertainty"} else (
        f"Residual {residual} {unit} exceeds the modeled uncertainty envelope; cause unresolved.",
    )
    return BalanceResult(
        _stable_id("AYL_RBR", {**base, "residual": residual, "status": status}),
        boundary.boundary_id, window.window_id, boundary.topology_state_id,
        boundary.resource_domain, unit, gross_input, gross_output, storage_change,
        documented_loss, expected_loss, residual, envelope, status, attribution,
        facts, inferences, excluded,
    )


def to_canonical_dict(value: Any) -> dict[str, Any]:
    """Serialize one contract object for schema validation or frozen fixtures."""
    return json.loads(json.dumps(asdict(value)))


CONTRACT_TYPES = {
    cls.__name__: cls for cls in (
        ResourceAsset, ResourceFlowEdge, ResourceObservation, StorageState,
        ConversionProcess, BalanceBoundary, BalanceWindow, ExpectedLossModel,
        UncertaintyEnvelope, BalanceResult, ResidualAttribution, TopologyState,
        InvestigationCase,
    )
}
