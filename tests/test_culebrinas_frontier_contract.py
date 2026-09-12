import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_culebrinas_contract_fail_closed():
    contract = json.loads((ROOT / ".federation/culebrinas-spatial-evidence-contract.json").read_text())
    assert contract["contract"] == "federation.spatial-evidence/1.0"
    assert contract["gates"]["canonical_aquifer_feature"] == "BLOCKED_FEATURE_EXTRACTION"
    assert contract["gates"]["measured_kvi"] == "BLOCKED_NO_FIELD_DATA"
    assert contract["certification"] == "OPEN_BLOCKED_EXPERIMENTAL"


def test_culebrinas_checkpoint_does_not_claim_measurement():
    checkpoint = json.loads((ROOT / "data/culebrinas/frontier/v2/certification_checkpoint_v2.json").read_text())
    assert checkpoint["states"]["new_field_observations"] == "BLOCKED_NOT_COLLECTED"
    assert checkpoint["states"]["kvi_measured"] == "BLOCKED_NO_FIELD_DATA"
    assert checkpoint["invariants"]["measured_kvi_not_synthesized"] is True
