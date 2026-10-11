"""Hydromet store: append-only merge, whole-event retention, manifestation closure,
fail-closed integrity, receipts and freshness."""
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from aguayluz.hazard_plane import (
    EntityKind,
    EvidenceClass,
    HazardFamily,
    HazardRecord,
    HazardRelationship,
    RecordKind,
    RecordStatus,
    RelationshipType,
)
from aguayluz.hydromet import store

NOW = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)


def _man(tag: str):
    return store.freeze_bytes(
        "nwps_gauges", tag.encode(), source_authority="NWS", source_system="NWPS API v1",
        source_record_id=f"gauges/{tag}", source_url="https://example.invalid", retrieved_at=NOW,
    )


def _rec(lid: str, man_id: str, *, supersedes=None, rev="a", observed=NOW):
    return HazardRecord(
        record_id=f"NWPS_GAUGE:{lid}:REV:{rev}",
        canonical_event_id=f"NWPS_GAUGE:{lid}",
        record_kind=RecordKind.OBSERVATION,
        family=HazardFamily.HYDROMETEOROLOGY,
        hazard_type="RIVER_STAGE_FLOOD_CATEGORY",
        source_authority="NWS",
        source_record_id=lid,
        manifestation_id=man_id,
        title_raw=lid,
        status=RecordStatus.PROVISIONAL,
        observed_from=observed,
        supersedes_record_id=supersedes,
    )


def _rel(record_id: str, man_ids):
    return HazardRelationship(
        relationship_id=store.relationship_id(record_id, "SAME_LOCATION", "USGS_1"),
        subject_id=record_id,
        predicate=RelationshipType.SAME_LOCATION,
        object_id="USGS_1",
        object_kind=EntityKind.FACILITY,
        evidence_class=EvidenceClass.STABLE_ID,
        source_manifestation_ids=list(man_ids),
    )


def test_freeze_bytes_hashes_exact_bytes_and_keeps_snapshot(tmp_path):
    man = store.freeze_bytes(
        "nwps_gauges", b'{"gauges": []}', source_authority="NWS", source_system="s",
        source_record_id="gauges", source_url="u", retrieved_at=NOW,
        headers={"ETag": '"abc"', "Last-Modified": "Wed"}, snapshot_dir=tmp_path, extension="json",
    )
    assert man.byte_sha256 == hashlib.sha256(b'{"gauges": []}').hexdigest()
    assert man.manifestation_id == f"HYDROMET:nwps_gauges:{man.byte_sha256[:32]}"
    assert (tmp_path / f"{man.byte_sha256}.json").read_bytes() == b'{"gauges": []}'
    assert man.http_etag == '"abc"' and man.http_last_modified == "Wed"


def test_apply_is_append_only_and_idempotent(tmp_path):
    m = _man("one")
    r = _rec("AIBP4", m.manifestation_id)
    run = store.SourceRun("nwps_gauges", manifestations=[m], records=[r],
                          relationships=[_rel(r.record_id, [m.manifestation_id])])
    first = store.apply_source_run(run, tmp_path)
    assert first["records_added"] == 1 and first["integrity"] == "PASS"
    before = store.hydromet_paths(tmp_path).records.read_bytes()
    second = store.apply_source_run(run, tmp_path)
    assert second["records_added"] == 0 and second["relationships_added"] == 0
    assert store.hydromet_paths(tmp_path).records.read_bytes() == before


def test_source_may_only_write_its_own_prefix(tmp_path):
    m = _man("x")
    foreign = _rec("AIBP4", m.manifestation_id).model_copy(update={"canonical_event_id": "OTHER:1"})
    with pytest.raises(ValueError, match="may only write"):
        store.apply_source_run(store.SourceRun("nwps_gauges", [m], [foreign]), tmp_path)
    with pytest.raises(ValueError, match="unknown hydromet source"):
        store.apply_source_run(store.SourceRun("nope", [m], []), tmp_path)


def test_unreferenced_manifestations_are_pruned(tmp_path):
    used, orphan = _man("used"), _man("orphan")
    r = _rec("AIBP4", used.manifestation_id)
    result = store.apply_source_run(store.SourceRun("nwps_gauges", [used, orphan], [r]), tmp_path)
    assert result["manifestations_pruned"] == 1
    kept = {m.manifestation_id for m in store.load_manifestations(tmp_path)}
    assert kept == {used.manifestation_id}


def test_receipt_references_keep_state_manifestations(tmp_path):
    state_man = _man("state")
    store.apply_source_run(store.SourceRun("nwps_gauges", [state_man], []), tmp_path,
                           referenced_manifestation_ids={state_man.manifestation_id})
    store.record_receipt("nwps_gauges", status="PASS", attempted_at=NOW, data_dir=tmp_path,
                         summary={}, referenced_manifestation_ids={state_man.manifestation_id})
    # A later run that adds nothing must not prune what the receipt still points at.
    store.apply_source_run(store.SourceRun("nwps_gauges", [], []), tmp_path)
    assert {m.manifestation_id for m in store.load_manifestations(tmp_path)} == {state_man.manifestation_id}
    assert store.integrity(tmp_path)["state"] == "PASS"


def test_missing_state_manifestation_fails_integrity(tmp_path):
    store.record_receipt("nwps_gauges", status="PASS", attempted_at=NOW, data_dir=tmp_path,
                         summary={}, referenced_manifestation_ids={"HYDROMET:nwps_gauges:gone"})
    report = store.integrity(tmp_path)
    assert report["state"] == "FAIL"
    assert "MISSING_STATE_MANIFESTATIONS" in report["unresolved"]


def test_dangling_supersedes_fails_closed_and_writes_nothing(tmp_path):
    m = _man("m")
    bad = _rec("AIBP4", m.manifestation_id, supersedes="NWPS_GAUGE:AIBP4:REV:missing", rev="b")
    with pytest.raises(ValueError, match="integrity"):
        store.apply_source_run(store.SourceRun("nwps_gauges", [m], [bad]), tmp_path)
    assert not store.hydromet_paths(tmp_path).records.exists()


def test_retention_drops_whole_events_with_their_relationships(tmp_path):
    m = _man("m")
    old_a = _rec("OLDP4", m.manifestation_id, rev="a", observed=NOW - timedelta(days=60))
    old_b = _rec("OLDP4", m.manifestation_id, rev="b", supersedes=old_a.record_id,
                 observed=NOW - timedelta(days=45))
    fresh = _rec("NEWP4", m.manifestation_id, rev="a")
    rels = [_rel(old_b.record_id, [m.manifestation_id]), _rel(fresh.record_id, [m.manifestation_id])]
    store.apply_source_run(store.SourceRun("nwps_gauges", [m], [old_a, old_b, fresh], rels), tmp_path)

    def keep(current):
        return current.observed_from >= NOW - timedelta(days=30)

    result = store.apply_source_run(store.SourceRun("nwps_gauges", retain_event=keep), tmp_path)
    assert result["events_pruned"] == 1
    assert [r.canonical_event_id for r in store.load_records(tmp_path)] == ["NWPS_GAUGE:NEWP4"]
    assert [r.subject_id for r in store.load_relationships(tmp_path)] == [fresh.record_id]


def test_revision_chains_follow_supersedes_and_current_is_the_tail():
    m = "man"
    a = _rec("AIBP4", m, rev="a")
    b = _rec("AIBP4", m, rev="b", supersedes=a.record_id)
    c = _rec("AIBP4", m, rev="c", supersedes=b.record_id)
    chains = store.revision_chains([c, a, b], "NWPS_GAUGE:")
    assert [r.record_id for r in chains["NWPS_GAUGE:AIBP4"]] == [a.record_id, b.record_id, c.record_id]
    assert store.current_by_event([c, a, b], "NWPS_GAUGE:")["NWPS_GAUGE:AIBP4"].record_id == c.record_id


def test_failed_attempt_keeps_last_success(tmp_path):
    store.record_receipt("nwps_gauges", status="PASS", attempted_at=NOW, data_dir=tmp_path,
                         summary={"arithmetic": {"state": "PASS"}}, referenced_manifestation_ids=["x"])
    later = NOW + timedelta(minutes=15)
    entry = store.record_receipt("nwps_gauges", status="FAIL", attempted_at=later,
                                 data_dir=tmp_path, error="bulk fetch failed: timeout")
    assert entry["last_status"] == "FAIL"
    assert entry["last_error"].startswith("bulk fetch failed")
    assert entry["last_success_utc"] == "2026-10-07T20:00:00Z"
    assert entry["last_success"] == {"arithmetic": {"state": "PASS"}}
    assert entry["referenced_manifestation_ids"] == ["x"]
    with pytest.raises(ValueError):
        store.record_receipt("nwps_gauges", status="MAYBE", attempted_at=NOW, data_dir=tmp_path)


@pytest.mark.parametrize(
    ("receipt", "age", "expected"),
    [
        (None, None, "NEVER"),
        ({"last_status": "PASS", "last_success_utc": "2026-10-07T19:30:00Z"}, None, "FRESH"),
        ({"last_status": "PASS", "last_success_utc": "2026-10-07T10:00:00Z"}, None, "STALE"),
        ({"last_status": "FAIL", "last_success_utc": "2026-10-07T19:30:00Z"}, None, "FAILED"),
        ({"last_status": "FAIL", "last_success_utc": None}, None, "FAILED"),
        ({"last_status": "PASS", "last_success_utc": "garbage"}, None, "NEVER"),
    ],
)
def test_freshness_states(receipt, age, expected):
    source = {"max_age_seconds": 7200}
    assert store.freshness(receipt, source, NOW)["state"] == expected


def test_registry_lookup_and_missing_config(tmp_path):
    registry = store.load_source_registry()
    assert store.registry_source("nwps_gauges", registry)["refresh_script"] == "scripts/ingest_nwps_gauges.py"
    assert store.registry_source("missing", registry) is None
    broken = store.load_source_registry(tmp_path / "absent.json")
    assert broken["sources"] == [] and broken["unresolved_material"]


def test_read_jsonl_rejects_non_objects(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"a": 1}\n\n[1, 2]\n')
    with pytest.raises(ValueError, match="non-object"):
        store.read_jsonl(path)
    assert store.read_jsonl(tmp_path / "absent.jsonl") == []
    store.write_json(tmp_path / "x.json", {"b": 1})
    assert store.read_json(tmp_path / "x.json") == {"b": 1}
    assert store.read_json(tmp_path / "absent.json", default=7) == 7


def test_accounting_appends(tmp_path):
    store.append_accounting({"run": 1}, tmp_path)
    store.append_accounting({"run": 2}, tmp_path)
    assert len(store.read_jsonl(store.hydromet_paths(tmp_path).accounting)) == 2
