import json

import pytest

from scripts.ingest_sdwis_hazard_plane import (
    FrozenPage,
    classify_row,
    fetch_pages,
    process_pages,
)

from aguayluz.hazard_plane import HazardRecord, RecordKind, current_records


def _raw(rows):
    return json.dumps(rows, sort_keys=True).encode("utf-8")


def _row(**overrides):
    row = {
        "pwsid": "PR0002000",
        "violation_id": "V-1",
        "violation_code": "21",
        "violation_category_code": "MCL",
        "rule_group_code": "100",
        "contaminant_code": "3100",
        "is_health_based_ind": "Y",
        "public_notification_tier": "1",
        "compliance_status_code": "O",
        "compl_per_begin_date": "2026-09-15 00:00:00",
        "compl_per_end_date": "2026-09-30 00:00:00",
        "population_served_count": "1000",
    }
    row.update(overrides)
    return row


def _page(rows, start=0):
    return FrozenPage(
        url=f"fixture://sdwis/{start}",
        raw=_raw(rows),
        headers={"etag": "fixture"},
        start=start,
    )


def _read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_bounded_source_arithmetic_classifies_complete_source_query(tmp_path):
    rows = [
        _row(violation_id="V-retained"),
        _row(violation_id="V-nonhealth", is_health_based_ind="N"),
        _row(violation_id="V-old", compl_per_begin_date="2025-09-15 00:00:00"),
        _row(violation_id="V-unresolved", is_health_based_ind=""),
    ]

    result = process_pages([_page(rows)], year=2026, output_root=tmp_path)

    assert result["source_arithmetic"] == {
        "source": 4,
        "retained": 1,
        "excluded": 2,
        "unresolved": 1,
        "accounted": 4,
        "delta": 0,
        "state": "PASS",
    }
    assert result["certification_state"] == "OPEN"
    assert result["boil_water_inference_permitted"] is False
    assert result["consumer_action_semantics"] == "UNRESOLVED_WITHOUT_EXPLICIT_PUBLIC_NOTICE"
    records = [HazardRecord.model_validate(row) for row in _read_jsonl(tmp_path / "hazard_records.jsonl")]
    assert len(records) == 1
    assert records[0].record_kind == RecordKind.OBSERVATION


def test_zero_unresolved_fixture_can_close_bounded_denominator(tmp_path):
    rows = [
        _row(violation_id="V-retained"),
        _row(violation_id="V-nonhealth", is_health_based_ind="N"),
        _row(violation_id="V-old", compl_per_begin_date="2025-09-15 00:00:00"),
    ]

    result = process_pages(
        [_page(rows)],
        year=2026,
        output_root=tmp_path,
        require_zero_unresolved=True,
    )

    assert result["source_arithmetic"]["unresolved"] == 0
    assert result["certification_state"] == "PASS"


def test_require_zero_unresolved_fails_closed_after_preserving_receipt(tmp_path):
    with pytest.raises(ValueError, match="unresolved"):
        process_pages(
            [_page([_row(is_health_based_ind="")])],
            year=2026,
            output_root=tmp_path,
            require_zero_unresolved=True,
        )
    receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["certification_state"] == "OPEN"
    assert receipt["source_arithmetic"]["unresolved"] == 1


def test_replaying_same_source_row_is_logically_idempotent(tmp_path):
    page = _page([_row()])
    first = process_pages([page], year=2026, output_root=tmp_path)
    second = process_pages([page], year=2026, output_root=tmp_path)

    assert first["new_record_revisions"] == 1
    assert second["new_record_revisions"] == 0
    assert len(_read_jsonl(tmp_path / "hazard_records.jsonl")) == 1
    assert len(_read_jsonl(tmp_path / "hazard_manifestations.jsonl")) == 2


def test_changed_source_row_creates_superseding_revision(tmp_path):
    old = _row()
    revised = _row(compliance_status_code="R")

    process_pages([_page([old])], year=2026, output_root=tmp_path)
    result = process_pages([_page([revised])], year=2026, output_root=tmp_path)

    assert result["new_record_revisions"] == 1
    rows = [
        HazardRecord.model_validate(row)
        for row in _read_jsonl(tmp_path / "hazard_records.jsonl")
    ]
    assert len(rows) == 2
    current = current_records(rows)
    assert len(current) == 1
    assert current[0].raw_attributes["compliance_status_code"] == "R"
    assert current[0].supersedes_record_id is not None


def test_missing_source_identity_is_unresolved_not_invented():
    disposition, reason = classify_row(
        _row(pwsid="", violation_id=""),
        2026,
    )
    assert (disposition, reason) == ("UNRESOLVED", "MISSING_STABLE_SOURCE_ID")


class _Response:
    def __init__(self, content):
        self.content = content
        self.headers = {}

    def raise_for_status(self):
        return None


class _MutatingClient:
    def __init__(self):
        self.calls = 0

    def get(self, _url):
        self.calls += 1
        if self.calls == 1:
            return _Response(_raw([_row()]))
        return _Response(_raw([_row(compliance_status_code="R")]))


def test_live_fetch_fails_closed_when_source_changes_during_snapshot():
    with pytest.raises(ValueError, match="changed during pagination"):
        fetch_pages(_MutatingClient(), page_size=10)
