from __future__ import annotations

import importlib.util
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
    for i in range(77):
        docs.append({
            "municipality": f"M{i:02d}",
            "document_class": "flood_risk_zone_map",
            "source_series": "JP_SECTORES_EN_ZONA_INUNDABLES",
            "equivalent_series_member": True,
            "source_url": f"https://example.test/{i}.pdf",
        })
    docs.append({
        "municipality": "Florida",
        "document_class": "hazard_mitigation_plan",
        "source_series": "JP_FLORIDA_HAZARD_MITIGATION_PLAN",
        "equivalent_series_member": False,
        "source_url": "https://example.test/florida.pdf",
        "relationship_to_series": "authoritative_alternate_not_equivalent",
        "series_absence_state": "outside_source_series_provisional",
    })
    return {
        "manifest_version": "1.0",
        "authority": "Junta de Planificación de Puerto Rico",
        "portal_url": "https://example.test/",
        "documents": docs,
    }


def test_consumer_preserves_77_plus_1_contract() -> None:
    out = mod.build_lookup(_manifest())
    assert out["counts"] == {
        "municipalities": 78,
        "flood_risk_zone_maps": 77,
        "authoritative_alternates": 1,
    }
    assert out["by_municipality"]["Florida"]["document_class"] == "hazard_mitigation_plan"
    assert out["by_municipality"]["Florida"]["equivalent_series_member"] is False


def test_florida_series_promotion_fails_closed() -> None:
    m = _manifest()
    m["documents"][-1]["document_class"] = "flood_risk_zone_map"
    m["documents"][-1]["equivalent_series_member"] = True
    with pytest.raises(ValueError):
        mod.build_lookup(m)


def test_duplicate_municipality_fails_closed() -> None:
    m = _manifest()
    m["documents"][1]["municipality"] = m["documents"][0]["municipality"]
    with pytest.raises(ValueError):
        mod.build_lookup(m)
