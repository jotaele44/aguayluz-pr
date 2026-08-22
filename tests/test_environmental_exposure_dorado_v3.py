from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "research/environmental_exposure/dorado_well_hydrogeology_lineage.v1.json"


def load_manifest():
    return json.loads(MANIFEST.read_text("utf-8"))


def test_historical_well_snapshots_are_date_bound_and_not_current_claims():
    data = load_manifest()
    snapshots = {row["snapshot_id"]: row for row in data["temporal_snapshots"]}
    assert snapshots["EPA_HRS_2015_WELL_STATUS"]["effective_period"] == "2015"
    assert snapshots["EPA_PROPOSED_PLAN_2021"]["effective_period"] == "2021"
    assert snapshots["EPA_HRS_2015_WELL_STATUS"]["wells"]
    assert all(row["status_state"] == "HISTORICAL_2015" for row in snapshots["EPA_HRS_2015_WELL_STATUS"]["wells"])
    assert snapshots["EPA_PROPOSED_PLAN_2021"]["state"] == "HISTORICAL_SNAPSHOT_ONLY"


def test_system_label_conflict_is_preserved_open():
    data = load_manifest()
    conflict = data["temporal_conflicts"][0]
    assert conflict["conflict_id"] == "MAGUAYO_DORADO_SYSTEM_LABEL_NEVAREZ_SANTA_ROSA"
    assert conflict["state"] == "OPEN"
    assert "do not normalize" in conflict["adjudication_rule"].lower()


def test_usgs_stable_ids_are_preserved_without_current_status_promotion():
    data = load_manifest()
    by_id = {row["usgs_site_no"]: row for row in data["usgs_stable_identities"]}
    assert {"182548066164401", "182548066164400", "182526066165000", "50047300"} <= set(by_id)
    assert all(row["current_status_claimed"] is False for row in by_id.values())
    santa_rosa = by_id["182526066165000"]
    assert santa_rosa["national_aquifer_code"] == "N400NCSTLM"
    assert santa_rosa["local_aquifer_code"] == "122NRCSU"


def test_vertical_extent_and_target_hydraulic_connection_remain_open():
    data = load_manifest()
    assert data["epa_ri_ffs_well_universe"]["vertical_extent_state"].startswith("OPEN")
    assert data["vertical_profile_evidence"]["full_vertical_plume_extent_claimed"] is False
    target = data["target_adjudication"]
    assert target["nearest_well_is_hydrologic_connection"] is False
    assert target["same_regional_aquifer_is_hydrologic_connection"] is False
    assert target["target_to_plume_hydraulic_connection_state"] == "UNRESOLVED"
    assert target["specific_plume_source_state"] == "AUTHORITATIVELY_UNKNOWN"
    assert target["production_relationship_promotion"] == "BLOCKED"


def test_receptor_relations_do_not_imply_source_attribution():
    data = load_manifest()
    assert data["receptor_relationships"]
    assert all(row["source_attribution_implication"] == "NONE" for row in data["receptor_relationships"])
