from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ingest_jp_flood_documents.py"
spec = importlib.util.spec_from_file_location("jp_flood_consumer", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

def _manifest() -> dict:
    docs = []
    for i in range(76):
        docs.append(
            {
                "municipality": f"M{i:02d}",
                "document_class": "flood_risk_zone_map",
                "source_series": "JP_SECTORES_EN_ZONA_INUNDABLES",
                "equivalent_series_member": True,
                "source_url": f"https://example.test/{i}.pdf",
                "source_state": "AVAILABLE",
            }
        )
    docs.append(
        {
            "municipality": "Quebradillas",
            "document_class": "flood_risk_zone_map",
            "source_series": "JP_SECTORES_EN_ZONA_INUNDABLES",
            "equivalent_series_member": True,
            "source_url": "https://example.test/quebradillas-broken.pdf",
            "source_state": "LISTED_BUT_MISSING",
            "fallback_document_class": "hazard_mitigation_plan",
            "fallback_source_url": "https://example.test/quebradillas-hmp.pdf",
            "fallback_source_access_state": "REMOTE_FORBIDDEN_OR_UNRELIABLE",
            "fallback_operational_mode": "frozen_local_manifestation",
            "fallback_relationship": "authoritative_fallback_not_equivalent",
            "frozen_manifestation": {
                "filename": "Quebradillas.pdf",
                "byte_size": 51_199_142,
                "sha256": "a1a2ccbfe0097da6f531e78f834d01be5a1555700b809d8f68b162db83d23e7a",
                "identity_scope": "byte_manifestation",
            },
        }
    )
    docs.append(
        {
            "municipality": "Florida",
            "document_class": None,
            "source_series": "JP_SECTORES_EN_ZONA_INUNDABLES",
            "equivalent_series_member": False,
            "source_url": None,
            "source_state": "NOT_LISTED",
            "fallback_document_class": "hazard_mitigation_plan",
            "fallback_source_url": "https://example.test/florida-hmp.pdf",
            "fallback_operational_mode": "remote_fetch",
            "fallback_relationship": "authoritative_fallback_not_equivalent",
        }
    )
    return {
        "manifest_version": "2.1",
        "authority": "Junta de Planificación de Puerto Rico",
        "portal_url": "https://example.test/",
        "documents": docs,
    }

def test_consumer_preserves_source_states_and_fallbacks() -> None:
    out = mod.build_lookup(_manifest())
    assert out["counts"] == {
        "municipalities": 78,
        "available_flood_maps": 76,
        "listed_but_missing": 1,
        "not_listed": 1,
        "authoritative_fallbacks": 2,
        "operational_coverage": 78,
    }
    q = out["by_municipality"]["Quebradillas"]
    assert q["source_state"] == "LISTED_BUT_MISSING"
    assert q["operational_document_class"] == "hazard_mitigation_plan"
    assert q["operational_access_mode"] == "frozen_local_manifestation"
    assert q["operational_source_url"] is None
    assert q["provenance_fallback_source_url"] == "https://example.test/quebradillas-hmp.pdf"
    assert q["sha256"] == mod.QUEBRADILLAS_FROZEN_SHA256
    assert q["byte_size"] == mod.QUEBRADILLAS_FROZEN_BYTE_SIZE
    assert out["by_municipality"]["Florida"]["source_state"] == "NOT_LISTED"

def test_quebradillas_operational_hash_mismatch_fails_closed() -> None:
    manifest = _manifest()
    manifest["documents"][-2]["operational_document"] = {
        "sha256": "bad",
        "byte_size": mod.QUEBRADILLAS_FROZEN_BYTE_SIZE,
    }
    with pytest.raises(ValueError, match="operational SHA256 mismatch"):
        mod.build_lookup(manifest)

def test_quebradillas_promotion_fails_closed() -> None:
    manifest = _manifest()
    manifest["documents"][-2]["source_state"] = "AVAILABLE"
    with pytest.raises(ValueError):
        mod.build_lookup(manifest)

def test_duplicate_municipality_fails_closed() -> None:
    manifest = _manifest()
    manifest["documents"][1]["municipality"] = manifest["documents"][0]["municipality"]
    with pytest.raises(ValueError):
        mod.build_lookup(manifest)


def test_canonical_producer_contract_is_bound_by_exact_bytes() -> None:
    contract_path = ROOT / "data" / "jp_flood_documents_producer_contract.json"
    contract = mod.validate_producer_contract(contract_path)
    assert contract["schema_version"] == mod.PRODUCER_CONTRACT_SCHEMA
    assert contract["producer_merge_sha"] == mod.PRODUCER_MERGE_SHA
    assert hashlib.sha256(contract_path.read_bytes()).hexdigest() == mod.PRODUCER_CONTRACT_SHA256


def test_wrong_producer_contract_hash_fails_closed(tmp_path) -> None:
    source = ROOT / "data" / "jp_flood_documents_producer_contract.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["producer"] = "tampered-producer"
    bad = tmp_path / "producer_contract.json"
    bad.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="producer contract SHA256 mismatch"):
        mod.validate_producer_contract(bad)


def test_altered_producer_contract_arithmetic_fails_even_with_matching_hash(
    tmp_path, monkeypatch
) -> None:
    source = ROOT / "data" / "jp_flood_documents_producer_contract.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["source_contract"]["series_available"] = 75
    bad = tmp_path / "producer_contract.json"
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    bad.write_bytes(raw)

    monkeypatch.setattr(mod, "PRODUCER_CONTRACT_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="series_available mismatch"):
        mod.validate_producer_contract(bad)
