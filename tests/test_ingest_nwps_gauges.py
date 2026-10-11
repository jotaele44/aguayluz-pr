"""scripts/ingest_nwps_gauges.py end to end, offline.

Positive inputs are the real captures under tests/fixtures/ (6 PR gauges). Cases that
need a shape NWPS did not happen to publish during capture — a non-PR gauge, an entry
without coordinates, a category change — are CONSTRUCTED from those captures and say so.
"""
import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from aguayluz.hydromet import store  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
BULK = FIXTURES / "nwps_pr_gauges_sample.json"
DETAILS = FIXTURES / "nwps_gauge_details"
ASSETS = REPO / "data" / "utility_assets.jsonl"

_SPEC = importlib.util.spec_from_file_location("ingest_nwps_gauges", REPO / "scripts" / "ingest_nwps_gauges.py")
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest  # dataclasses resolve annotations through sys.modules
_SPEC.loader.exec_module(ingest)


def run(data_dir, *extra, src=BULK, now="2026-10-07T20:00:00Z"):
    return ingest.main([
        "--src", str(src), "--details-src", str(DETAILS), "--data-dir", str(data_dir),
        "--assets", str(ASSETS), "--now", now, *extra,
    ])


def test_offline_run_closes_arithmetic_and_binds(tmp_path):
    assert run(tmp_path) == 0
    receipt = store.load_receipts(tmp_path)["sources"]["nwps_gauges"]
    summary = receipt["last_success"]
    assert receipt["last_status"] == "PASS"
    assert summary["arithmetic"] == {
        "source": 6, "retained": 6, "excluded": 0, "unresolved": 0,
        "accounted": 6, "delta": 0, "state": "PASS",
    }
    assert summary["integrity"] == "PASS"
    state = {row["lid"]: row for row in store.load_gauge_state(tmp_path)}
    assert set(state) == {"AIBP4", "QUEP4", "CAGP4", "ESPP4", "NGIP4", "TRUP4"}
    assert state["QUEP4"]["flood_category"] == "minor"
    assert state["QUEP4"]["asset_id"] == "USGS_50010800"  # STABLE_ID join on usgsId
    assert state["CAGP4"]["geoid"] is None and state["CAGP4"]["binding_evidence"] == "UNRESOLVED"
    assert state["ESPP4"]["asset_id"] is None  # tide gauge: NWPS publishes no usgsId
    # every record and binding traces back to a frozen manifestation
    assert store.integrity(tmp_path)["state"] == "PASS"
    rels = store.load_relationships(tmp_path)
    stable = [r for r in rels if r.evidence_class.value == "STABLE_ID"]
    assert {r.object_id for r in stable} >= {"USGS_50010800", "USGS_50043000"}
    snapshots = list(store.hydromet_paths(tmp_path).snapshot_dir("nwps_gauges").glob("*.json"))
    assert len(snapshots) == 7  # bulk + 6 details, named by their SHA-256


def test_rerun_is_byte_identical_except_current_state(tmp_path):
    assert run(tmp_path) == 0
    paths = store.hydromet_paths(tmp_path)
    before = {p: p.read_bytes() for p in (paths.records, paths.relationships, paths.manifestations)}
    assert run(tmp_path, now="2026-10-07T20:15:00Z") == 0
    for path, content in before.items():
        assert path.read_bytes() == content, path.name
    receipt = store.load_receipts(tmp_path)["sources"]["nwps_gauges"]["last_success"]
    assert receipt["new_revisions"] == 0
    assert receipt["details_fetched"] == 0  # details < 24 h old are reused from state


def test_dry_run_writes_nothing(tmp_path, capsys):
    assert run(tmp_path, "--dry-run") == 0
    assert list(tmp_path.iterdir()) == []
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["arithmetic"]["state"] == "PASS"


def test_unreadable_source_writes_fail_receipt_and_keeps_data(tmp_path):
    assert run(tmp_path) == 0
    records_before = store.hydromet_paths(tmp_path).records.read_bytes()
    broken = tmp_path / "broken.json"
    broken.write_text('{"not_gauges": []}')
    assert run(tmp_path, src=broken, now="2026-10-07T20:30:00Z") == 1
    receipt = store.load_receipts(tmp_path)["sources"]["nwps_gauges"]
    assert receipt["last_status"] == "FAIL"
    assert "gauges" in receipt["last_error"]
    assert receipt["last_success_utc"] == "2026-10-07T20:00:00Z"
    assert store.hydromet_paths(tmp_path).records.read_bytes() == records_before


def test_category_change_appends_a_superseding_revision(tmp_path):
    assert run(tmp_path) == 0
    # CONSTRUCTED: AIBP4 crosses its action stage (real capture with the category edited).
    doc = json.loads(BULK.read_text())
    for gauge in doc["gauges"]:
        if gauge["lid"] == "AIBP4":
            gauge["status"]["observed"]["floodCategory"] = "action"
            gauge["status"]["observed"]["primary"] = 16.2
            gauge["status"]["observed"]["validTime"] = "2026-10-07T20:15:00Z"
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(doc))
    assert run(tmp_path, src=edited, now="2026-10-07T20:20:00Z") == 0
    chain = store.revision_chains(store.load_records(tmp_path), "NWPS_GAUGE:")["NWPS_GAUGE:AIBP4"]
    assert [r.normalized_values["flood_category"] for r in chain] == ["no_flooding", "action"]
    assert chain[1].supersedes_record_id == chain[0].record_id
    assert store.integrity(tmp_path)["state"] == "PASS"


def test_non_pr_and_malformed_entries_are_counted_not_dropped(tmp_path):
    # CONSTRUCTED: a USVI gauge and an entry with no coordinates added to the real capture.
    doc = json.loads(BULK.read_text())
    usvi = copy.deepcopy(doc["gauges"][0])
    usvi.update(lid="CHAV3", state={"abbreviation": "VI", "name": "Virgin Islands"})
    nocoord = copy.deepcopy(doc["gauges"][0])
    nocoord.update(lid="XXXP4", latitude=None)
    doc["gauges"] += [usvi, nocoord, "not-an-object"]
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(doc))
    assert run(tmp_path, src=edited) == 0
    summary = store.load_receipts(tmp_path)["sources"]["nwps_gauges"]["last_success"]
    assert summary["arithmetic"]["source"] == 9
    assert summary["arithmetic"]["retained"] == 6
    assert summary["arithmetic"]["excluded"] == 1
    assert summary["arithmetic"]["unresolved"] == 2
    assert summary["outcomes"]["excluded:state_VI"] == 1


def test_missing_detail_keeps_gauge_without_thresholds(tmp_path):
    details = tmp_path / "details"
    shutil.copytree(DETAILS, details)
    (details / "QUEP4.json").unlink()
    code = ingest.main([
        "--src", str(BULK), "--details-src", str(details), "--data-dir", str(tmp_path),
        "--assets", str(ASSETS), "--now", "2026-10-07T20:00:00Z",
    ])
    assert code == 0
    quep = next(r for r in store.load_gauge_state(tmp_path) if r["lid"] == "QUEP4")
    assert quep["thresholds"] == {} and quep["asset_id"] is None
    assert quep["detail_error"] == "NO_DETAIL"


def test_classify_and_needs_detail_helpers():
    assert ingest.classify({"lid": "A", "latitude": 18.2, "longitude": -66.5,
                            "state": {"abbreviation": "PR"}}) == "retained"
    assert ingest.classify({"lid": "A", "latitude": 25.0, "longitude": -80.0,
                            "state": {"abbreviation": "PR"}}) == "excluded:outside_pr_envelope"
    assert ingest.classify({}) == "unresolved:missing_lid"
    now = ingest.adapter.parse_time("2026-10-07T20:00:00Z")
    assert ingest.needs_detail(None, now, 24)
    assert ingest.needs_detail({"detail": {"lid": "A"}, "detail_retrieved_at": "2026-10-05T00:00:00Z"}, now, 24)
    assert not ingest.needs_detail({"detail": {"lid": "A"}, "detail_retrieved_at": "2026-10-07T10:00:00Z"}, now, 24)
    assert ingest.needs_detail({"detail": {"lid": "A"}, "detail_error": "boom",
                                "detail_retrieved_at": "2026-10-07T10:00:00Z"}, now, 24)
    assert ingest.schema_signature([{"b": 1, "a": 2}]) == "nwps.gauges[a,b]"


def test_bad_clock_override_is_rejected(tmp_path):
    assert run(tmp_path, now="yesterday") == 2
