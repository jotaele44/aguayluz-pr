import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fia_manifest_is_frozen_and_fail_closed():
    manifest = json.loads((ROOT / "data-sources/usfs/fia/fiadb/pr/manifest/source_manifest.json").read_text())
    assert manifest["sha256"] == "338b0bf6e088d94d7c9c170ba1850f50b682829670519d72325a36b9ee8d3965"
    assert manifest["csv_members"] == 68
    assert manifest["data_rows"] == 431380
    assert manifest["spatial_precision_class"] == "FIA_PUBLIC_PROTECTED"
    assert manifest["exact_site_identity_allowed"] is False
    assert manifest["certification"] != "CERTIFIED"
    assert manifest["open_residue"]


def test_environmental_contract_forbids_proximity_identity():
    contract = json.loads((ROOT / ".federation/environmental-source-contract.json").read_text())
    rules = "\n".join(contract["rules"])
    assert "public coordinate" in rules
    assert "proximity" in rules
    assert "M:N multiplication fails closed" in rules
    assert "future updates become new manifestations" in rules
