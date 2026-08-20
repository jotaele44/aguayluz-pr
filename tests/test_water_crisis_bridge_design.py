import json
from pathlib import Path

import pytest

from aguayluz.water_crisis_bridge import map_candidate_to_alert

FIXTURE = Path(__file__).parent / "fixtures" / "water_crisis_assessments_v0_1.jsonl"


def _rows():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def test_all_five_assessment_codes_are_covered():
    rows = _rows()
    assert {r["assessment_code"] for r in rows} == {
        "CARRAIZO_RATIONING_RISK",
        "CUPEY_DISTRIBUTION_RECOVERY_FAILURE",
        "ISLANDWIDE_RESERVOIR_DECLINE",
        "LOCO_RESERVOIR_OBSERVATION",
        "CONTAMINATION_EVENT",
    }


def test_zero_auto_promotion_and_zero_active_status():
    for row in _rows():
        alert = map_candidate_to_alert(row)
        assert alert["review_status"] != "accepted"
        assert alert["status"] != "active"
        assert alert["water_crisis_extension"]["promotion_status"] == "candidate"
        assert "no automatic verified promotion" in alert["validation_notes"]


def test_unverified_contamination_is_blocked():
    row = next(r for r in _rows() if r["assessment_code"] == "CONTAMINATION_EVENT")
    alert = map_candidate_to_alert(row)
    assert alert["module_id"] == "CONTAMINATION"
    assert alert["review_status"] == "blocked"
    assert alert["status"] == "draft"
    assert alert["gap_status"] == "blocking"


def test_conflicting_cupey_evidence_remains_needs_review():
    row = next(r for r in _rows() if r["assessment_code"] == "CUPEY_DISTRIBUTION_RECOVERY_FAILURE")
    alert = map_candidate_to_alert(row)
    assert alert["review_status"] == "needs_review"
    assert alert["gap_status"] == "major"
    assert "Repair completed" in alert["validation_notes"]


def test_replay_is_deterministic():
    row = _rows()[0]
    assert map_candidate_to_alert(row) == map_candidate_to_alert(row)


def test_non_candidate_input_is_rejected():
    row = _rows()[0]
    row["promotion_status"] = "verified"
    with pytest.raises(ValueError, match="candidate records only"):
        map_candidate_to_alert(row)
