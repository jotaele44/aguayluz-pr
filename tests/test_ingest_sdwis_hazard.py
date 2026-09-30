import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.ingest_sdwis_violations import FrozenPage, process_pages

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROWS = json.loads(
    (ROOT / "tests" / "fixtures" / "sdwis_violations_sample.json").read_text()
)


def _page(rows, *, table="VIOLATION", start=0):
    raw = json.dumps(rows, sort_keys=True).encode()
    return FrozenPage(
        table=table,
        url=f"https://data.epa.gov/efservice/{table}/test",
        raw=raw,
        headers={"etag": '"test-etag"'},
        start=start,
        end=start + max(len(rows) - 1, 0),
    )


def _process(tmp_path, rows, *, retrieved_at, require_zero_unresolved=False):
    return process_pages(
        [_page(rows)],
        [],
        output_root=tmp_path,
        retrieved_at=retrieved_at,
        require_zero_unresolved=require_zero_unresolved,
        write_legacy=False,
        legacy_out=tmp_path / "service_events.jsonl",
        muni_geojson=ROOT / "data" / "geo" / "pr_municipios.geojson",
    )


def test_source_arithmetic_classifies_every_bounded_row(tmp_path):
    valid_a = dict(FIXTURE_ROWS[0])
    valid_b = dict(FIXTURE_ROWS[1])
    missing_identity = dict(FIXTURE_ROWS[2])
    missing_identity["violation_id"] = None
    outside_pr = dict(FIXTURE_ROWS[3])
    outside_pr["pwsid"] = "NY0002000"

    receipt = _process(
        tmp_path,
        [valid_a, valid_b, missing_identity, outside_pr],
        retrieved_at=datetime(2026, 9, 30, 20, 0, tzinfo=timezone.utc),
    )

    assert receipt["source_arithmetic"] == {
        "source": 4,
        "retained": 2,
        "excluded": 1,
        "unresolved": 1,
        "accounted": 4,
        "delta": 0,
        "state": "PASS",
    }
    assert receipt["certification_state"] == "OPEN"


def test_same_snapshot_replay_is_logically_idempotent_but_freezes_manifestation(tmp_path):
    first = _process(
        tmp_path,
        FIXTURE_ROWS,
        retrieved_at=datetime(2026, 9, 30, 20, 1, tzinfo=timezone.utc),
        require_zero_unresolved=True,
    )
    second = _process(
        tmp_path,
        FIXTURE_ROWS,
        retrieved_at=datetime(2026, 9, 30, 20, 2, tzinfo=timezone.utc),
        require_zero_unresolved=True,
    )

    assert first["new_record_revisions"] == len(FIXTURE_ROWS)
    assert second["new_record_revisions"] == 0
    assert first["source_arithmetic"]["unresolved"] == 0
    assert second["source_arithmetic"]["unresolved"] == 0

    manifestations = [
        json.loads(line)
        for line in (tmp_path / "hazard_manifestations.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(manifestations) == 2
    assert manifestations[0]["byte_sha256"] == manifestations[1]["byte_sha256"]
    assert manifestations[0]["manifestation_id"] != manifestations[1]["manifestation_id"]


def test_changed_source_row_creates_one_superseding_revision(tmp_path):
    original = dict(FIXTURE_ROWS[2])
    revised = dict(original)
    revised["compliance_status_code"] = "R"

    _process(
        tmp_path,
        [original],
        retrieved_at=datetime(2026, 9, 30, 20, 3, tzinfo=timezone.utc),
        require_zero_unresolved=True,
    )
    receipt = _process(
        tmp_path,
        [revised],
        retrieved_at=datetime(2026, 9, 30, 20, 4, tzinfo=timezone.utc),
        require_zero_unresolved=True,
    )

    assert receipt["new_record_revisions"] == 1
    records = [
        json.loads(line)
        for line in (tmp_path / "hazard_records.jsonl").read_text().splitlines()
        if line.strip()
    ]
    event_rows = [
        row
        for row in records
        if row["canonical_event_id"] == "EPA_SDWIS:PR0002591:9001234"
    ]
    assert len(event_rows) == 2
    current = next(row for row in event_rows if row["supersedes_record_id"] is not None)
    prior = next(row for row in event_rows if row["record_id"] == current["supersedes_record_id"])
    assert current["record_id"] != prior["record_id"]
    assert current["status"] == "TERMINATED"


def test_conflicting_duplicate_identity_fails_closed_as_unresolved(tmp_path):
    first = dict(FIXTURE_ROWS[0])
    conflicting = dict(first)
    conflicting["population_served_count"] = 999

    receipt = _process(
        tmp_path,
        [first, conflicting],
        retrieved_at=datetime(2026, 9, 30, 20, 5, tzinfo=timezone.utc),
    )

    assert receipt["source_arithmetic"]["source"] == 2
    assert receipt["source_arithmetic"]["retained"] == 1
    assert receipt["source_arithmetic"]["unresolved"] == 1
    assert receipt["source_arithmetic"]["delta"] == 0
    assert any(
        row["reason"] == "CONFLICTING_DUPLICATE_IDENTITY_IN_SNAPSHOT"
        for row in receipt["classifications"]
    )


def test_canonical_projection_keeps_geography_unbound_except_authoritative_pwsid(tmp_path):
    _process(
        tmp_path,
        [FIXTURE_ROWS[3]],
        retrieved_at=datetime(2026, 9, 30, 20, 6, tzinfo=timezone.utc),
        require_zero_unresolved=True,
    )
    record = json.loads(
        next(
            line
            for line in (tmp_path / "hazard_records.jsonl").read_text().splitlines()
            if line.strip()
        )
    )

    assert record["water_system_id"] == "PR0002000"
    assert record["municipality_id"] is None
    assert record["facility_id"] is None
    assert record["geometry_precision"] == "WATER_SYSTEM_ID_ONLY"
    assert record["raw_attributes"]["boil_water_advisory_evidence"] == (
        "NOT_ESTABLISHED_BY_SDWIS_VIOLATION_ALONE"
    )
