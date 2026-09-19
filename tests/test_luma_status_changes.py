"""Regression gates for conservative MiLUMA snapshot-diff semantics."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import derive_luma_status_changes as changes  # noqa: E402


def _row(ts: str, digest: str) -> dict:
    return {
        "snapshot_id": f"S_{ts}_{digest[:4]}",
        "snapshot_ts": ts,
        "payload_sha256": digest,
        "raw_payload": {"opaque": digest},
        "schema_state": "RAW_UNFROZEN",
    }


def test_changed_payload_does_not_certify_restoration():
    result = changes.classify_pair(
        _row("2026-09-19T08:00:00Z", "a" * 64),
        _row("2026-09-19T08:01:00Z", "b" * 64),
    )
    assert result["observation"] == "SOURCE_STATE_CHANGE"
    assert result["restoration_state"] == "UNRESOLVED"
    assert result["outage_lifecycle_state"] == "UNRESOLVED"


def test_identical_payload_is_source_state_unchanged():
    result = changes.classify_pair(
        _row("2026-09-19T08:00:00Z", "a" * 64),
        _row("2026-09-19T08:01:00Z", "a" * 64),
    )
    assert result["observation"] == "SOURCE_STATE_UNCHANGED"
    assert result["restoration_state"] == "UNRESOLVED"


def test_adjacent_diff_is_deterministic_and_row_conserving():
    rows = [
        _row("2026-09-19T08:02:00Z", "c" * 64),
        _row("2026-09-19T08:00:00Z", "a" * 64),
        _row("2026-09-19T08:01:00Z", "b" * 64),
    ]
    first = changes.derive_changes(rows)
    second = changes.derive_changes(list(reversed(rows)))

    assert first == second
    assert len(first) == len(rows) - 1
    assert [r["current_snapshot_ts"] for r in first] == [
        "2026-09-19T08:01:00Z",
        "2026-09-19T08:02:00Z",
    ]


def test_empty_and_single_snapshot_have_no_synthetic_change():
    assert changes.derive_changes([]) == []
    assert changes.derive_changes([_row("2026-09-19T08:00:00Z", "a" * 64)]) == []
