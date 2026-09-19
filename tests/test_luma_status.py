"""Regression gates for MiLUMA regional outage-status wiring."""
import json
import sys
import urllib.error
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import fetch_luma_live  # noqa: E402
import ingest_luma_status  # noqa: E402


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_fetch_regions_preserves_source_shape(monkeypatch):
    payload = [
        {"region": "A", "customersWithoutService": 12},
        {"region": "B", "customersWithoutService": 0},
    ]
    monkeypatch.setattr(
        fetch_luma_live.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(payload),
    )

    assert fetch_luma_live.fetch_regions(timeout=1.0) == payload


def test_fetch_regions_403_is_source_unavailable(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            fetch_luma_live.REGIONS_URL,
            403,
            "Forbidden",
            {},
            None,
        )

    monkeypatch.setattr(fetch_luma_live.urllib.request, "urlopen", _raise)
    with pytest.raises(fetch_luma_live.SourceUnavailable):
        fetch_luma_live.fetch_regions(timeout=1.0)


def test_status_snapshot_preserves_raw_and_hashes_deterministically():
    payload = {"regions": [{"name": "Metro", "n": 3}], "unknown": None}
    row_a = ingest_luma_status.snapshot_row(
        payload,
        "2026-09-19T08:00:00Z",
        fetch_luma_live.REGIONS_URL,
    )
    row_b = ingest_luma_status.snapshot_row(
        payload,
        "2026-09-19T08:00:00Z",
        fetch_luma_live.REGIONS_URL,
    )

    assert row_a == row_b
    assert row_a["raw_payload"] == payload
    assert row_a["schema_state"] == "RAW_UNFROZEN"
    assert len(row_a["payload_sha256"]) == 64


def test_append_history_is_idempotent_and_row_conserving(tmp_path):
    out = tmp_path / "luma_status_snapshots.jsonl"
    row = ingest_luma_status.snapshot_row(
        [{"region": "Metro", "affected": 4}],
        "2026-09-19T08:00:00Z",
        fetch_luma_live.REGIONS_URL,
    )

    count1, added1 = ingest_luma_status.append_idempotent(out, row)
    count2, added2 = ingest_luma_status.append_idempotent(out, row)
    stored = [
        json.loads(line)
        for line in out.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert (count1, added1) == (1, True)
    assert (count2, added2) == (1, False)
    assert stored == [row]


def test_live_fetch_failure_removes_stale_temp_outputs(monkeypatch, tmp_path):
    towns = tmp_path / "towns.json"
    status = tmp_path / "status.json"
    towns.write_text('{"STALE": []}', encoding="utf-8")
    status.write_text('{"stale": true}', encoding="utf-8")

    def _fail(*_args, **_kwargs):
        raise fetch_luma_live.SourceUnavailable("blocked")

    monkeypatch.setattr(fetch_luma_live, "fetch_towns", _fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_luma_live.py",
            "--geo",
            str(REPO / "data/geo/pr_municipios.json"),
            "--out",
            str(towns),
            "--status-out",
            str(status),
        ],
    )

    assert fetch_luma_live.main() == fetch_luma_live.EXIT_SOURCE_UNAVAILABLE
    assert not towns.exists()
    assert not status.exists()
