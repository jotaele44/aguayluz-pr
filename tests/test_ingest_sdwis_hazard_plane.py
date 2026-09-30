import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from scripts import ingest_sdwis_violations as ingest

from aguayluz.hazard_plane import HazardRecord, RecordStatus, current_records

ROOT = Path(__file__).resolve().parents[1]
VIOL_PATH = ROOT / "tests" / "fixtures" / "sdwis_violations_sample.json"
GEO_PATH = ROOT / "tests" / "fixtures" / "sdwis_geographic_area_sample.json"
CANON = ingest.load_muni_canonical(ROOT / "data" / "geo" / "pr_municipios.geojson")


def _pages(path):
    return [(str(path), path.read_bytes(), {})]


def _page(rows):
    return [
        (
            "fixture://sdwis",
            json.dumps(rows, sort_keys=True).encode("utf-8"),
            {},
        )
    ]


def _configure_paths(monkeypatch, tmp_path):
    class DeterministicDatetime:
        current = datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            value = cls.current
            cls.current += timedelta(microseconds=1)
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(ingest, "datetime", DeterministicDatetime)
    monkeypatch.setattr(ingest, "HAZARD_RAW_ROOT", tmp_path / "snapshots")
    monkeypatch.setattr(ingest, "HAZARD_RECORDS_PATH", tmp_path / "hazard_records.jsonl")
    monkeypatch.setattr(
        ingest,
        "HAZARD_MANIFESTATIONS_PATH",
        tmp_path / "hazard_manifestations.jsonl",
    )
    monkeypatch.setattr(
        ingest,
        "HAZARD_LEDGER_PATH",
        tmp_path / "hazard_source_accounting.jsonl",
    )


def _read_jsonl(path):
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_sdwis_source_denominators_close_without_notice_claim(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)
    result = ingest.materialize_hazard_plane(
        _pages(VIOL_PATH),
        _pages(GEO_PATH),
        CANON,
        dry_run=True,
    )

    assert result["source_arithmetic"]["VIOLATION"] == {
        "source": 5,
        "retained": 5,
        "excluded": 0,
        "unresolved": 0,
        "accounted": 5,
        "delta": 0,
        "state": "PASS",
    }
    assert result["source_arithmetic"]["GEOGRAPHIC_AREA"] == {
        "source": 2,
        "retained": 2,
        "excluded": 0,
        "unresolved": 0,
        "accounted": 2,
        "delta": 0,
        "state": "PASS",
    }
    assert result["new_record_revisions"] == 5
    assert result["manifestations"] == 2
    assert result["advisory_issuance_claimed"] is False
    assert result["enforcement_action_denominator_closed"] is False


def test_live_style_materialization_freezes_bytes_and_is_replay_idempotent(
    monkeypatch,
    tmp_path,
):
    _configure_paths(monkeypatch, tmp_path)
    violation_pages = _pages(VIOL_PATH)
    geo_pages = _pages(GEO_PATH)

    first = ingest.materialize_hazard_plane(
        violation_pages,
        geo_pages,
        CANON,
        dry_run=False,
    )
    second = ingest.materialize_hazard_plane(
        violation_pages,
        geo_pages,
        CANON,
        dry_run=False,
    )

    assert first["new_record_revisions"] == 5
    assert second["new_record_revisions"] == 0

    records = _read_jsonl(ingest.HAZARD_RECORDS_PATH)
    manifests = _read_jsonl(ingest.HAZARD_MANIFESTATIONS_PATH)
    assert len(records) == 5
    assert len(manifests) == 4

    violation_sha = sha256(VIOL_PATH.read_bytes()).hexdigest()
    violation_manifests = [
        row for row in manifests if row["source_record_id"].startswith("VIOLATION:")
    ]
    assert len(violation_manifests) == 2
    assert {row["byte_sha256"] for row in violation_manifests} == {violation_sha}
    assert len({row["manifestation_id"] for row in violation_manifests}) == 2

    snapshots = list((tmp_path / "snapshots").rglob("*.json"))
    assert len(snapshots) == 4


def test_multi_municipio_geography_stays_one_to_many(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)
    ingest.materialize_hazard_plane(
        _pages(VIOL_PATH),
        _pages(GEO_PATH),
        CANON,
        dry_run=False,
    )
    rows = _read_jsonl(ingest.HAZARD_RECORDS_PATH)
    target = next(
        row
        for row in rows
        if row["canonical_event_id"] == "EPA_SDWIS:PR0002000:VIOLATION:9100777"
    )

    attrs = target["raw_attributes"]
    assert attrs["geography_binding_state"] == "1:N"
    assert attrs["municipality_name"] is None
    assert attrs["municipality_candidates"] == ["Bayamón", "San Juan", "Toa Alta"]


def test_changed_violation_source_row_creates_superseding_revision(
    monkeypatch,
    tmp_path,
):
    _configure_paths(monkeypatch, tmp_path)
    base = {
        "pwsid": "PR0002000",
        "violation_id": "X-1",
        "violation_code": "1A",
        "is_health_based_ind": "Y",
        "public_notification_tier": "1",
        "rule_group_code": "100",
        "compliance_status_code": "O",
        "compl_per_begin_date": "2026-01-01 00:00:00",
    }
    revised = {**base, "compliance_status_code": "R"}

    ingest.materialize_hazard_plane(_page([base]), [], CANON, dry_run=False)
    result = ingest.materialize_hazard_plane(_page([revised]), [], CANON, dry_run=False)

    assert result["new_record_revisions"] == 1
    rows = [
        HazardRecord.model_validate(row)
        for row in _read_jsonl(ingest.HAZARD_RECORDS_PATH)
    ]
    assert len(rows) == 2
    current = current_records(rows)
    assert len(current) == 1
    assert current[0].status == RecordStatus.TERMINATED
    assert current[0].supersedes_record_id is not None


def test_non_pr_and_identifierless_rows_are_accounted_not_silently_dropped(
    monkeypatch,
    tmp_path,
):
    _configure_paths(monkeypatch, tmp_path)
    rows = [
        {
            "pwsid": "US0000001",
            "violation_id": "outside",
            "compliance_status_code": "O",
        },
        {
            "pwsid": "PR0002000",
            "violation_id": "",
            "compliance_status_code": "O",
        },
        {
            "pwsid": "PR0002000",
            "violation_id": "retained",
            "compliance_status_code": "O",
        },
    ]
    result = ingest.materialize_hazard_plane(_page(rows), [], CANON, dry_run=True)

    assert result["source_arithmetic"]["VIOLATION"] == {
        "source": 3,
        "retained": 1,
        "excluded": 1,
        "unresolved": 1,
        "accounted": 3,
        "delta": 0,
        "state": "PASS",
    }
