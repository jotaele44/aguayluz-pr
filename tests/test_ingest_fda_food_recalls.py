import json
from datetime import datetime, timedelta, timezone

from scripts import ingest_fda_food_recalls as ingest

from aguayluz.hazard_plane import HazardRecord, current_records


def _page(rows):
    return json.dumps(
        {"meta": {"results": {"total": len(rows)}}, "results": rows},
        sort_keys=True,
    ).encode("utf-8")


def _configure_paths(monkeypatch, tmp_path):
    class DeterministicDatetime:
        current = datetime(2026, 9, 30, 15, 30, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            value = cls.current
            cls.current += timedelta(microseconds=1)
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(ingest, "datetime", DeterministicDatetime)
    monkeypatch.setattr(ingest, "RECORDS_PATH", tmp_path / "hazard_records.jsonl")
    monkeypatch.setattr(ingest, "MANIFESTATIONS_PATH", tmp_path / "hazard_manifestations.jsonl")
    monkeypatch.setattr(ingest, "LEDGER_PATH", tmp_path / "hazard_source_accounting.jsonl")
    monkeypatch.setattr(ingest, "RAW_ROOT", tmp_path / "snapshots")


def _read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_bounded_source_arithmetic_closes_without_pr_text_search(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)
    rows = [
        {
            "recall_number": "F-1000-2026",
            "product_description": "Explicit PR product",
            "distribution_pattern": "Puerto Rico",
            "status": "Ongoing",
        },
        {
            "recall_number": "F-1001-2026",
            "product_description": "National candidate",
            "distribution_pattern": "Nationwide",
            "status": "Ongoing",
        },
        {
            "recall_number": "F-1002-2026",
            "product_description": "California only",
            "distribution_pattern": "California",
            "status": "Ongoing",
        },
        {
            "recall_number": "F-1003-2026",
            "product_description": "Missing distribution",
            "distribution_pattern": "",
            "status": "Ongoing",
        },
    ]

    result = ingest.process_pages(
        [("fixture://fda", _page(rows), {})],
        dry_run=True,
    )

    assert result["source_arithmetic"] == {
        "source": 4,
        "retained": 2,
        "excluded": 1,
        "unresolved": 1,
        "accounted": 4,
        "delta": 0,
        "state": "PASS",
    }
    assert result["new_record_revisions"] == 2


def test_replaying_same_snapshot_is_logically_idempotent(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)
    rows = [
        {
            "recall_number": "F-2000-2026",
            "product_description": "Product",
            "distribution_pattern": "Puerto Rico",
            "status": "Ongoing",
        }
    ]
    pages = [("fixture://fda", _page(rows), {"etag": "fixture-v1"})]

    first = ingest.process_pages(pages, dry_run=False)
    second = ingest.process_pages(pages, dry_run=False)

    assert first["new_record_revisions"] == 1
    assert second["new_record_revisions"] == 0
    records = _read_jsonl(ingest.RECORDS_PATH)
    manifestations = _read_jsonl(ingest.MANIFESTATIONS_PATH)
    assert len(records) == 1
    assert len(manifestations) == 2
    assert manifestations[0]["byte_sha256"] == manifestations[1]["byte_sha256"]
    assert manifestations[0]["manifestation_id"] != manifestations[1]["manifestation_id"]


def test_changed_source_row_creates_one_superseding_revision(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)
    old = {
        "recall_number": "F-3000-2026",
        "product_description": "Product",
        "distribution_pattern": "Puerto Rico",
        "status": "Ongoing",
    }
    revised = {
        **old,
        "status": "Terminated",
        "termination_date": "20260929",
    }

    ingest.process_pages([("fixture://fda", _page([old]), {})], dry_run=False)
    result = ingest.process_pages([("fixture://fda", _page([revised]), {})], dry_run=False)

    assert result["new_record_revisions"] == 1
    rows = [HazardRecord.model_validate(row) for row in _read_jsonl(ingest.RECORDS_PATH)]
    assert len(rows) == 2
    current = current_records(rows)
    assert len(current) == 1
    assert current[0].raw_attributes["source_row"]["status"] == "Terminated"
    prior = next(row for row in rows if row.record_id == current[0].supersedes_record_id)
    assert prior.canonical_event_id == current[0].canonical_event_id
