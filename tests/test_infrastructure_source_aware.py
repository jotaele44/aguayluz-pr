from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_REGISTRY = ROOT / "ontology" / "infrastructure_terms.v0.1.json"
OVERLAY = ROOT / "ontology" / "source_aware_crosswalk.v0.1.json"
TOOL = ROOT / "ontology" / "tools" / "audit_infrastructure_source_aware.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("audit_infrastructure_source_aware", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_overlay_targets_existing_base_terms_and_has_unique_pairs():
    base = load_json(BASE_REGISTRY)
    overlay = load_json(OVERLAY)
    term_ids = {term["term_id"] for term in base["terms"]}
    keys = []
    for mapping in overlay["mappings"]:
        assert mapping["canonical_term_id"] in term_ids
        keys.append((mapping["legacy_asset_type"], mapping["legacy_asset_subtype"]))
    assert len(keys) == len(set(keys))


def test_source_aware_overlay_does_not_duplicate_base_crosswalk():
    base = load_json(BASE_REGISTRY)
    overlay = load_json(OVERLAY)
    base_keys = {
        (item["legacy_asset_type"], item["legacy_asset_subtype"])
        for item in base["legacy_crosswalk"]
    }
    overlay_keys = {
        (item["legacy_asset_type"], item["legacy_asset_subtype"])
        for item in overlay["mappings"]
    }
    assert base_keys.isdisjoint(overlay_keys)


def test_merge_registry_keeps_base_immutable():
    tool = load_tool()
    base = load_json(BASE_REGISTRY)
    before = json.dumps(base, sort_keys=True)
    merged = tool.merge_registry(base, load_json(OVERLAY))
    assert json.dumps(base, sort_keys=True) == before
    assert len(merged["legacy_crosswalk"]) == len(base["legacy_crosswalk"]) + len(load_json(OVERLAY)["mappings"])


def test_expected_count_gate_fails_on_snapshot_drift():
    tool = load_tool()
    overlay = {
        "mappings": [
            {
                "legacy_asset_type": "water",
                "legacy_asset_subtype": "stream_gage",
                "expected_current_rows": 2,
            }
        ]
    }
    rows = [{"asset_type": "water", "asset_subtype": "stream_gage"}]
    result = tool.validate_expected_counts(rows, overlay)
    assert result["pass"] is False
    assert result["checks"][0]["observed_current_rows"] == 1


def test_source_aware_direct_pairs_classify_without_identity_claim():
    tool = load_tool()
    base_tool = tool._load_base_tool()
    merged = tool.merge_registry(load_json(BASE_REGISTRY), load_json(OVERLAY))
    rows = [
        {"asset_id":"A","asset_type":"wastewater","asset_subtype":"wastewater_treatment","source_ref":"PR_Geodata/wastewater_plant.geojson (OSM)"},
        {"asset_id":"B","asset_type":"water","asset_subtype":"stream_gage","source_ref":"USGS NWIS Site Service, site 1"},
        {"asset_id":"C","asset_type":"water","asset_subtype":"treatment","source_ref":"PR_Geodata/water_treatment_plant.geojson (OSM)"},
        {"asset_id":"D","asset_type":"power","asset_subtype":"Generation (Water)","source_ref":"EIA Form 860"},
    ]
    decisions, summary = base_tool.classify_rows(rows, merged)
    assert summary["state_counts"] == {"provisional": 4}
    assert [d["canonical_term_id"] for d in decisions] == [
        "AYL_TERM_WASTEWATER_TREATMENT_PLANT",
        "AYL_TERM_SURFACE_WATER_GAGE",
        "AYL_TERM_WATER_TREATMENT_PLANT",
        "AYL_TERM_HYDROELECTRIC_GENERATOR",
    ]


def test_unlisted_umbrella_pairs_remain_unresolved():
    tool = load_tool()
    base_tool = tool._load_base_tool()
    merged = tool.merge_registry(load_json(BASE_REGISTRY), load_json(OVERLAY))
    rows = [
        {"asset_id":"A","asset_type":"water","asset_subtype":"waterworks","source_ref":"Waterworks_Integrated_v2.csv"},
        {"asset_id":"B","asset_type":"water","asset_subtype":"canal_feature","source_ref":"Canal_de_Riego_features_summary.csv"},
    ]
    decisions, summary = base_tool.classify_rows(rows, merged)
    assert summary["state_counts"] == {"unresolved": 2}
    assert all(d["canonical_term_id"] is None for d in decisions)
