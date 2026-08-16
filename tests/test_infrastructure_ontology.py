from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "ontology" / "infrastructure_terms.v0.1.json"
AUDIT_PATH = ROOT / "scripts" / "audit_infrastructure_vocabulary.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_infrastructure_vocabulary", AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_registry_term_ids_and_labels_are_unique():
    registry = load_registry()
    term_ids = [term["term_id"] for term in registry["terms"]]
    labels = [term["canonical_label"] for term in registry["terms"]]
    assert len(term_ids) == len(set(term_ids))
    assert len(labels) == len(set(labels))


def test_all_alias_targets_exist_and_aliases_do_not_claim_identity():
    registry = load_registry()
    term_ids = {term["term_id"] for term in registry["terms"]}
    for alias in registry["aliases"]:
        assert alias["canonical_term_id"] in term_ids
        assert alias["identity_effect"] == "none"


def test_ebas_is_regional_term_for_sanitary_sewer_pump_station():
    registry = load_registry()
    matches = [alias for alias in registry["aliases"] if alias["alias"].casefold() == "ebas"]
    assert len(matches) == 1
    assert matches[0]["alias_kind"] == "regional_term"
    assert matches[0]["canonical_term_id"] == "AYL_TERM_SANITARY_SEWER_PUMP_STATION"


def test_wet_well_is_component_not_ebas_or_site():
    registry = load_registry()
    by_id = {term["term_id"]: term for term in registry["terms"]}
    wet_well = by_id["AYL_TERM_WET_WELL"]
    ebas = by_id["AYL_TERM_SANITARY_SEWER_PUMP_STATION"]
    assert wet_well["feature_kind"] == "component"
    assert ebas["feature_kind"] == "asset"
    assert wet_well["term_id"] != ebas["term_id"]


def test_ambiguous_legacy_pump_station_fails_open_to_unresolved():
    registry = load_registry()
    rows = [
        {
            "asset_id": "LEGACY_1",
            "asset_type": "water",
            "asset_subtype": "pump_station",
            "source_ref": "fixture",
        }
    ]
    audit = load_audit_module()
    decisions, summary = audit.classify_rows(rows, registry)
    assert summary["state_counts"] == {"unresolved": 1}
    assert decisions[0]["canonical_term_id"] is None
    assert decisions[0]["classification_state"] == "unresolved"


def test_unknown_pair_is_not_nearest_matched():
    registry = load_registry()
    rows = [
        {
            "asset_id": "LEGACY_2",
            "asset_type": "wastewater",
            "asset_subtype": "mystery_station",
            "source_ref": "fixture",
        }
    ]
    audit = load_audit_module()
    decisions, _ = audit.classify_rows(rows, registry)
    assert decisions[0]["canonical_term_id"] is None
    assert decisions[0]["classification_state"] == "unresolved"


def test_candidate_outlet_never_becomes_certified_identity():
    registry = load_registry()
    rows = [
        {
            "asset_id": "LEGACY_3",
            "asset_type": "water",
            "asset_subtype": "coastal_outlet_candidate",
            "source_ref": "fixture",
        }
    ]
    audit = load_audit_module()
    decisions, _ = audit.classify_rows(rows, registry)
    assert decisions[0]["canonical_term_id"] == "AYL_TERM_COASTAL_OUTLET"
    assert decisions[0]["classification_state"] == "candidate_not_identity"


def test_raw_strings_are_preserved_separately_from_normalization():
    registry = load_registry()
    raw = "  Estación  DE-Bombas  "
    rows = [
        {
            "asset_id": "LEGACY_4",
            "asset_type": "wastewater",
            "asset_subtype": raw,
            "source_ref": "fixture",
        }
    ]
    audit = load_audit_module()
    decisions, _ = audit.classify_rows(rows, registry)
    decision = decisions[0]
    assert decision["legacy_asset_subtype_raw"] == raw
    assert decision["normalized_asset_subtype"] != raw
    assert decision["canonical_term_id"] is None


def test_audit_arithmetic_closes_on_mixed_fixture(tmp_path: Path):
    assets = tmp_path / "utility_assets.jsonl"
    rows = [
        {"asset_id":"A","asset_type":"water","asset_subtype":"treatment_plant","source_ref":"a"},
        {"asset_id":"B","asset_type":"water","asset_subtype":"pump_station","source_ref":"b"},
        {"asset_id":"C","asset_type":"wastewater","asset_subtype":"wastewater_plant","source_ref":"c"},
        {"asset_id":"D","asset_type":"water","asset_subtype":"coastal_outlet_candidate","source_ref":"d"},
    ]
    assets.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    audit = load_audit_module()
    report, decisions = audit.build_report(assets, REGISTRY_PATH)
    assert report["arithmetic"]["pass"] is True
    assert report["arithmetic"]["source_rows"] == 4
    assert report["arithmetic"]["closed_total"] == 4
    assert len(decisions) == 4
    assert report["certification_state"] == "provisional"


def test_registry_validator_passes():
    audit = load_audit_module()
    result = audit.validate_registry(load_registry())
    assert result["pass"] is True
