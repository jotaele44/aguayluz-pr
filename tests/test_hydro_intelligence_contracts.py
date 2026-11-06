"""Hydro registry contract negative/coverage tests; offline only."""
import copy
import json
from pathlib import Path

import pytest

from aguayluz.hydro_intelligence.contracts import validate_source_contract

ROOT = Path(__file__).resolve().parents[1]


def _registry():
    return json.loads((ROOT / "config" / "hydro_intelligence_sources.v1.json").read_text(
        encoding="utf-8"
    ))


def test_registry_declares_bounded_nonoperational_coverage():
    result = validate_source_contract(_registry())
    assert result["state"] == "CONTRACT_ONLY_NOT_RUNTIME"
    assert result["source_count"] == 5
    assert result["discovery_contract_count"] == 3
    assert result["source_specific_adapter_required_count"] == 2
    assert result["operational_ingestion"] is False
    assert result["canonical_promotion"] is False
    assert all(row["acquisition_state"] == "NOT_ASSERTED" for row in result["sources"])


@pytest.mark.parametrize("mutation", [
    "duplicate_id", "missing_field", "unsafe_url", "unknown_type",
    "disable_raw", "invalid_interval", "claim_runtime",
])
def test_registry_rejects_unsupported_or_unsafe_contract(mutation):
    registry = copy.deepcopy(_registry())
    first = registry["source_families"][0]
    if mutation == "duplicate_id":
        registry["source_families"][1]["source_id"] = first["source_id"]
    elif mutation == "missing_field":
        del first["index_url"]
    elif mutation == "unsafe_url":
        first["index_url"] = "http://127.0.0.1/private"
    elif mutation == "unknown_type":
        first["artifact_type"] = "guessed"
    elif mutation == "disable_raw":
        first["raw_byte_required"] = False
    elif mutation == "invalid_interval":
        first["discovery_interval_hours"] = 0
    elif mutation == "claim_runtime":
        registry["implementation_state"] = "PRODUCTION"
    with pytest.raises(ValueError):
        validate_source_contract(registry)
