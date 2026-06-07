"""Tests for `aguayluz.history.snapshot_run` and `diff_runs`."""

from __future__ import annotations

import json

from aguayluz.history import diff_runs, list_snapshots, snapshot_run
from aguayluz.models import validate_against_schema


def _write_state(
    outputs_dir,  # type: ignore[no-untyped-def]
    *,
    assets,
    events=None,
    findings=None,
) -> None:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "utility_assets.json").write_text(json.dumps(assets), encoding="utf-8")
    (outputs_dir / "service_events.json").write_text(json.dumps(events or []), encoding="utf-8")
    if findings is not None:
        (outputs_dir / "reconciliation_report.json").write_text(
            json.dumps({"findings": findings, "summary": {}}),
            encoding="utf-8",
        )


def _asset(asset_id, **kw):  # type: ignore[no-untyped-def]
    base = {
        "asset_id": asset_id,
        "asset_type": "water",
        "asset_subtype": "intake",
        "municipality": "Toa Alta",
        "status": "active",
        "review_status": "accepted",
        "attribute_coverage": "full",
        "comid": 21000100,
        "reachcode": "21010002000001",
    }
    base.update(kw)
    return base


def _event(event_id, **kw):  # type: ignore[no-untyped-def]
    base = {
        "event_id": event_id,
        "event_type": "project_update",
        "review_status": "needs_review",
        "start_time": "2017-09-20T00:00:00Z",
        "end_time": None,
        "reported_customers_or_users": None,
        "notes": "step=Project Obligated",
    }
    base.update(kw)
    return base


# ---------- snapshot ----------


def test_snapshot_persists_entity_files(tmp_path):
    outputs = tmp_path / "outputs"
    _write_state(outputs, assets=[_asset("A1")])
    snap = snapshot_run(outputs, "20260606T120000Z_test")
    assert (snap / "utility_assets.json").exists()
    assert (snap / "_snapshot_at.txt").exists()


def test_snapshot_skips_missing_files(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    # No entity files at all.
    snap = snapshot_run(outputs, "20260606T120000Z_test")
    assert snap.exists()
    assert not (snap / "utility_assets.json").exists()
    # Tombstone is still written.
    assert (snap / "_snapshot_at.txt").exists()


def test_snapshot_overrides_history_root(tmp_path):
    outputs = tmp_path / "outputs"
    _write_state(outputs, assets=[_asset("A1")])
    custom_root = tmp_path / "elsewhere"
    snap = snapshot_run(outputs, "20260606T120000Z_test", history_root=custom_root)
    assert snap.parent == custom_root


def test_list_snapshots_sorted_chronologically(tmp_path):
    history_root = tmp_path / "history"
    history_root.mkdir()
    for name in ("20260606T120000Z_b", "20260606T100000Z_a", "20260606T140000Z_c"):
        (history_root / name).mkdir()
    assert list_snapshots(history_root) == [
        "20260606T100000Z_a",
        "20260606T120000Z_b",
        "20260606T140000Z_c",
    ]


def test_list_snapshots_missing_root_returns_empty(tmp_path):
    assert list_snapshots(tmp_path / "no_history") == []


# ---------- diff_runs ----------


def test_diff_no_changes_reports_zero(tmp_path):
    outputs = tmp_path / "outputs"
    _write_state(outputs, assets=[_asset("A1")], events=[_event("E1")])
    snapshot_run(outputs, "20260606T100000Z_a")
    snapshot_run(outputs, "20260606T110000Z_b")
    diff = diff_runs(
        history_root=outputs / "history",
        run_from="20260606T100000Z_a",
        run_to="20260606T110000Z_b",
    )
    assert diff["summary"]["total_changes"] == 0
    assert diff["summary"]["headline"] == "no changes between runs"
    validate_against_schema("run_diff", diff)


def test_diff_detects_added_asset(tmp_path):
    outputs = tmp_path / "outputs"
    _write_state(outputs, assets=[_asset("A1")])
    snapshot_run(outputs, "20260606T100000Z_a")
    _write_state(outputs, assets=[_asset("A1"), _asset("A2")])
    snapshot_run(outputs, "20260606T110000Z_b")
    diff = diff_runs(
        history_root=outputs / "history",
        run_from="20260606T100000Z_a",
        run_to="20260606T110000Z_b",
    )
    assert diff["assets_added"] == ["A2"]
    assert "+1" in diff["summary"]["headline"]


def test_diff_detects_removed_asset(tmp_path):
    outputs = tmp_path / "outputs"
    _write_state(outputs, assets=[_asset("A1"), _asset("A2")])
    snapshot_run(outputs, "20260606T100000Z_a")
    _write_state(outputs, assets=[_asset("A1")])
    snapshot_run(outputs, "20260606T110000Z_b")
    diff = diff_runs(
        history_root=outputs / "history",
        run_from="20260606T100000Z_a",
        run_to="20260606T110000Z_b",
    )
    assert diff["assets_removed"] == ["A2"]
    assert "-1" in diff["summary"]["headline"]


def test_diff_detects_status_change(tmp_path):
    outputs = tmp_path / "outputs"
    _write_state(outputs, assets=[_asset("A1", status="damaged")])
    snapshot_run(outputs, "20260606T100000Z_a")
    _write_state(outputs, assets=[_asset("A1", status="active")])
    snapshot_run(outputs, "20260606T110000Z_b")
    diff = diff_runs(
        history_root=outputs / "history",
        run_from="20260606T100000Z_a",
        run_to="20260606T110000Z_b",
    )
    assert len(diff["assets_changed"]) == 1
    change = diff["assets_changed"][0]
    assert change == {"asset_id": "A1", "field": "status", "from": "damaged", "to": "active"}


def test_diff_detects_event_status_flip(tmp_path):
    outputs = tmp_path / "outputs"
    _write_state(outputs, assets=[], events=[_event("E1", review_status="needs_review")])
    snapshot_run(outputs, "20260606T100000Z_a")
    _write_state(outputs, assets=[], events=[_event("E1", review_status="accepted")])
    snapshot_run(outputs, "20260606T110000Z_b")
    diff = diff_runs(
        history_root=outputs / "history",
        run_from="20260606T100000Z_a",
        run_to="20260606T110000Z_b",
    )
    assert any(
        c["field"] == "review_status" and c["from"] == "needs_review" and c["to"] == "accepted"
        for c in diff["events_changed"]
    )


def test_diff_finding_set_changes(tmp_path):
    outputs = tmp_path / "outputs"
    _write_state(
        outputs,
        assets=[],
        findings=[{"finding_id": "AYL_FIND_1"}, {"finding_id": "AYL_FIND_2"}],
    )
    snapshot_run(outputs, "20260606T100000Z_a")
    _write_state(
        outputs,
        assets=[],
        findings=[{"finding_id": "AYL_FIND_2"}, {"finding_id": "AYL_FIND_3"}],
    )
    snapshot_run(outputs, "20260606T110000Z_b")
    diff = diff_runs(
        history_root=outputs / "history",
        run_from="20260606T100000Z_a",
        run_to="20260606T110000Z_b",
    )
    assert diff["findings_added"] == ["AYL_FIND_3"]
    assert diff["findings_removed"] == ["AYL_FIND_1"]


def test_diff_missing_snapshot_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError, match="snapshot not found"):
        diff_runs(history_root=tmp_path / "history", run_from="ghost", run_to="phantom")


def test_diff_ignores_noisy_fields(tmp_path):
    """source_hash changes shouldn't propagate to the diff."""
    outputs = tmp_path / "outputs"
    _write_state(outputs, assets=[_asset("A1", source_hash="abc")])
    snapshot_run(outputs, "20260606T100000Z_a")
    _write_state(outputs, assets=[_asset("A1", source_hash="def")])
    snapshot_run(outputs, "20260606T110000Z_b")
    diff = diff_runs(
        history_root=outputs / "history",
        run_from="20260606T100000Z_a",
        run_to="20260606T110000Z_b",
    )
    # source_hash isn't in _ASSET_DIFF_FIELDS so the diff is empty.
    assert diff["summary"]["total_changes"] == 0


def test_diff_validates_against_schema_when_populated(tmp_path):
    outputs = tmp_path / "outputs"
    _write_state(outputs, assets=[_asset("A1")])
    snapshot_run(outputs, "20260606T100000Z_a")
    _write_state(outputs, assets=[_asset("A1"), _asset("A2")])
    snapshot_run(outputs, "20260606T110000Z_b")
    diff = diff_runs(
        history_root=outputs / "history",
        run_from="20260606T100000Z_a",
        run_to="20260606T110000Z_b",
    )
    validate_against_schema("run_diff", diff)
