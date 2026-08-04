from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/resource-balance/v0.1/resource_balance_contracts.schema.json"
CORE = runpy.run_path(str(ROOT / "research/resource_balance/core.py"))

BalanceBoundary = CORE["BalanceBoundary"]
BalanceWindow = CORE["BalanceWindow"]
CONTRACT_TYPES = CORE["CONTRACT_TYPES"]
ExpectedLossModel = CORE["ExpectedLossModel"]
ResourceObservation = CORE["ResourceObservation"]
compute_balance = CORE["compute_balance"]
resource_asset_from_utility_asset = CORE["resource_asset_from_utility_asset"]
resource_observation_from_monitoring_reading = CORE["resource_observation_from_monitoring_reading"]
to_canonical_dict = CORE["to_canonical_dict"]


def observation(identifier: str, role: str, amount: float, *, domain: str = "water", unit: str = "MG", uncertainty: float = 0.0, eligible: bool = True) -> ResourceObservation:
    return ResourceObservation(
        observation_id=identifier,
        asset_id="asset:pilot",
        resource_domain=domain,  # type: ignore[arg-type]
        quantity_kind="interval_total",
        role=role,  # type: ignore[arg-type]
        amount=amount,
        unit=unit,
        observed_at="2026-08-04T00:00:00-04:00",
        source_ref="fixture",
        evidence_tier="T1",
        confidence=95,
        review_status="accepted",
        uncertainty_abs=uncertainty,
        eligible_for_balance=eligible,
    )


def boundary(domain: str = "water") -> BalanceBoundary:
    return BalanceBoundary(
        boundary_id=f"boundary:{domain}:pilot",
        name="Pilot",
        resource_domain=domain,  # type: ignore[arg-type]
        asset_ids=("asset:pilot",),
        edge_ids=(),
        topology_state_id=f"topology:{domain}:20260804",
    )


def window() -> BalanceWindow:
    return BalanceWindow("window:20260804", "2026-08-04T00:00:00-04:00", "2026-08-05T00:00:00-04:00", "daily")


def test_contract_registry_has_thirteen_types() -> None:
    assert len(CONTRACT_TYPES) == 13
    assert {"ResourceAsset", "BalanceResult", "InvestigationCase"} <= set(CONTRACT_TYPES)


def test_schema_is_valid_and_has_thirteen_defs() -> None:
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    assert len(schema["$defs"]) == 13


def test_legacy_asset_wrapper_preserves_identity_and_provenance() -> None:
    legacy = SimpleNamespace(
        asset_id="EIA_1", asset_name="Plant", asset_type="power", asset_subtype="generator",
        operator="Operator", municipality="Peñuelas", status="active", source_ref="EIA-860",
        evidence_tier="T1", confidence=90, review_status="accepted",
    )
    wrapped = resource_asset_from_utility_asset(legacy)
    assert wrapped.resource_asset_id == "legacy:EIA_1"
    assert wrapped.legacy_asset_id == "EIA_1"
    assert wrapped.resource_domain == "electricity"
    assert wrapped.compatibility_mode == "legacy_wrapper"


def test_legacy_reading_is_context_only() -> None:
    wrapped = resource_observation_from_monitoring_reading({
        "reading_id": "AYL_RDG_20260804_X_generation", "asset_id": "EIA_1",
        "metric": "generation", "value": 10, "unit": "MWh", "observed_date": "2026-08-04",
        "source_ref": "fixture", "source_hash": None, "evidence_tier": "T1",
        "confidence": 90, "review_status": "accepted",
    })
    assert wrapped.role == "context"
    assert wrapped.eligible_for_balance is False
    assert wrapped.resource_domain == "electricity"


def test_water_balance_closes_exactly() -> None:
    result = compute_balance(boundary(), window(), [
        observation("rain", "inflow", 100), observation("outtake", "outflow", 70),
        observation("storage", "storage_change", 20), observation("flush", "documented_loss", 10),
    ])
    assert result.status == "balanced"
    assert result.residual == 0


def test_electrical_deficit_remains_unresolved() -> None:
    result = compute_balance(boundary("electricity"), window(), [
        observation("generation", "generation", 100, domain="electricity", unit="MWh"),
        observation("usage", "consumption", 82, domain="electricity", unit="MWh"),
    ], [ExpectedLossModel("loss:1", "boundary:electricity:pilot", "electricity", 8, "MWh", 1, "technical", "v1")])
    assert result.status == "unaccounted_deficit"
    assert result.residual == 10
    assert result.attribution.cause == "unresolved"
    assert "No theft" in result.attribution.notes[1]


def test_uncertainty_prevents_false_promotion() -> None:
    result = compute_balance(boundary(), window(), [
        observation("in", "inflow", 100, uncertainty=3),
        observation("out", "outflow", 96, uncertainty=4),
    ])
    assert result.uncertainty_envelope.absolute_tolerance == 5
    assert result.status == "within_uncertainty"


def test_context_only_input_is_insufficient() -> None:
    result = compute_balance(boundary(), window(), [observation("legacy", "context", 10, eligible=False)])
    assert result.status == "insufficient_data"
    assert result.excluded_observation_ids == ("legacy",)


def test_mixed_units_fail_closed() -> None:
    with pytest.raises(ValueError, match="one canonical unit"):
        compute_balance(boundary(), window(), [
            observation("a", "inflow", 1, unit="MG"), observation("b", "outflow", 1, unit="m3"),
        ])


def test_domain_mismatch_fails_closed_and_result_validates() -> None:
    with pytest.raises(ValueError, match="resource domain"):
        compute_balance(boundary(), window(), [observation("power", "generation", 1, domain="electricity", unit="MWh")])
    result = compute_balance(boundary(), window(), [observation("in", "inflow", 1), observation("out", "outflow", 1)])
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator(schema).validate(to_canonical_dict(result))
