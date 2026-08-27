from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "environmental_exposure"


def test_dorado_lust_2024_denominator_arithmetic_and_cross_list_conflict():
    data = json.loads((RESEARCH / "dorado_lust_2024_denominator.v1.json").read_text("utf-8"))
    active = data["active"]
    inactive = data["inactive"]

    assert len(active) == data["counts"]["active_manifestations"] == 2
    assert len(inactive) == data["counts"]["inactive_manifestations"] == 8
    assert len(active) + len(inactive) == data["counts"]["manifestation_total"] == 10
    ids = [row["ust_id"] for row in active + inactive]
    assert len(set(ids)) == data["counts"]["unique_ust_ids"] == 9
    assert sorted({value for value in ids if ids.count(value) > 1}) == ["86-0353"]
    assert data["cross_list_conflicts"][0]["ust_id"] == "86-0353"
    assert data["cross_list_conflicts"][0]["conflict_state"] == "OPEN"
    assert data["closure"]["source_attribution_state"] == "NOT_TESTED"
    assert data["closure"]["causal_claims"] == 0


def test_dorado_lust_rows_are_discovery_only():
    data = json.loads((RESEARCH / "dorado_lust_2024_denominator.v1.json").read_text("utf-8"))
    assert data["causal_promotion_allowed"] is False
    assert all(row["city"] == "Dorado" for row in data["active"] + data["inactive"])
    assert all(row["causal_state"] == "DISCOVERY_CANDIDATE" for row in data["active"] + data["inactive"])


def test_dorado_epa_2021_administrative_record_closes_14_row_index_only():
    data = json.loads((RESEARCH / "dorado_epa_administrative_record_2021.v1.json").read_text("utf-8"))
    docs = data["documents"]

    assert len(docs) == data["document_count"] == 14
    assert len({row["doc_id"] for row in docs}) == data["document_id_unique_count"] == 14
    assert data["closure"]["final_index_row_denominator_state"] == "EXHAUSTED_14_OF_14"
    assert data["closure"]["document_byte_acquisition_state"] == "OPEN"
    assert data["closure"]["attachments_and_embedded_files_state"] == "OPEN"
    assert data["closure"]["source_attribution_state"] == "AUTHORITATIVELY_UNKNOWN"


def test_v2_progress_remains_open_despite_bounded_subscope_closure():
    data = json.loads((RESEARCH / "source_denominator_progress.v2.json").read_text("utf-8"))
    assert data["overall_state"] == "OPEN"
    assert data["completeness_claimed"] is False
    controls = data["negative_attribution_controls"]
    assert controls["epa_site_source_state"] == "UNKNOWN"
    assert controls["lust_candidates_may_be_promoted"] is False
    assert controls["target_hydraulic_connection_state"] == "UNRESOLVED"
    assert controls["proximity_promotion_forbidden"] is True
