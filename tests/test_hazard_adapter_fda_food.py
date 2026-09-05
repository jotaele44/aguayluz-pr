from aguayluz.hazard_adapters.fda_food import (
    PR_EXPLICIT,
    PR_NATIONAL_CANDIDATE,
    PR_NO_INDICATION,
    classify_pr_relevance,
    normalize,
)
from aguayluz.hazard_plane import RecordStatus


def test_explicit_puerto_rico_distribution_is_confirmed():
    assert classify_pr_relevance({"distribution_pattern": "Puerto Rico and Florida"}) == PR_EXPLICIT


def test_nationwide_distribution_is_not_silently_promoted_to_pr_confirmation():
    assert classify_pr_relevance({"distribution_pattern": "Nationwide"}) == PR_NATIONAL_CANDIDATE


def test_absent_distribution_language_stays_no_indication():
    assert classify_pr_relevance({"distribution_pattern": "California only"}) == PR_NO_INDICATION


def test_normalize_preserves_raw_source_and_recall_identity():
    raw = {
        "recall_number": "F-1234-2026",
        "event_id": "99999",
        "classification": "Class I",
        "product_description": "Frozen product, lot ABC",
        "reason_for_recall": "Potential contamination",
        "distribution_pattern": "Puerto Rico",
        "status": "Ongoing",
        "recall_initiation_date": "20260801",
        "report_date": "20260812",
        "recalling_firm": "Example Foods",
    }
    record = normalize(raw, "manifest-fda-1")
    assert record.record_id == "FDA_FOOD_RECALL:F-1234-2026"
    assert record.status == RecordStatus.ACTIVE
    assert record.raw_attributes["source_row"] == raw
    assert record.raw_attributes["pr_relevance"] == PR_EXPLICIT
    assert record.geometry_precision == "NONE_UNLESS_INDEPENDENTLY_BOUND"


def test_terminated_status_and_dates_are_not_conflated():
    raw = {
        "recall_number": "F-2345-2026",
        "product_description": "Product",
        "status": "Terminated",
        "recall_initiation_date": "20260102",
        "report_date": "20260120",
        "termination_date": "20260301",
    }
    record = normalize(raw, "manifest-fda-2")
    assert record.status == RecordStatus.TERMINATED
    assert record.observed_from.date().isoformat() == "2026-01-02"
    assert record.reported_at.date().isoformat() == "2026-01-20"
    assert record.effective_to.date().isoformat() == "2026-03-01"
