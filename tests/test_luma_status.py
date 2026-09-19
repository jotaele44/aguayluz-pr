"""Regression gates for MiLUMA regional outage-status wiring."""
import hashlib
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
    def __init__(self, payload=None, raw=None):
        self._raw = raw if raw is not None else json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._raw


def test_fetch_regions_preserves_source_shape(monkeypatch):
    payload = [{"unverified": {"field": 12}}, {"other": None}]
    monkeypatch.setattr(
        fetch_luma_live.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(payload=payload),
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
        "a" * 64,
        123,
    )
    row_b = ingest_luma_status.snapshot_row(
        payload,
        "2026-09-19T08:00:00Z",
        fetch_luma_live.REGIONS_URL,
        "a" * 64,
        123,
    )

    assert row_a == row_b
    assert row_a["raw_payload"] == payload
    assert row_a["schema_state"] == "RAW_UNFROZEN"
    assert len(row_a["payload_sha256"]) == 64
    assert row_a["source_byte_sha256"] == "a" * 64
    assert row_a["source_byte_count"] == 123


def test_append_history_is_idempotent_and_row_conserving(tmp_path):
    out = tmp_path / "luma_status_snapshots.jsonl"
    row = ingest_luma_status.snapshot_row(
        [{"region": "Metro", "affected": 4}],
        "2026-09-19T08:00:00Z",
        fetch_luma_live.REGIONS_URL,
        "b" * 64,
        99,
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


def test_regional_failure_does_not_discard_valid_town_snapshot(monkeypatch, tmp_path):
    towns = tmp_path / "towns.json"
    status = tmp_path / "status.json"
    manifest = tmp_path / "manifest.json"
    towns_raw = b'{"SAN JUAN":[{"zone":"A","area":"B"}]}'
    calls = 0

    def _urlopen(req, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _Response(raw=towns_raw)
        raise urllib.error.HTTPError(
            fetch_luma_live.REGIONS_URL,
            403,
            "Forbidden",
            {},
            None,
        )

    monkeypatch.setattr(fetch_luma_live.urllib.request, "urlopen", _urlopen)
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
            "--manifest-out",
            str(manifest),
        ],
    )

    assert fetch_luma_live.main() == 0
    assert towns.read_bytes() == towns_raw
    assert not status.exists()
    receipt = json.loads(manifest.read_text(encoding="utf-8"))
    assert receipt["towns"]["status"] == "PASS"
    assert receipt["towns"]["response_sha256"] == hashlib.sha256(towns_raw).hexdigest()
    assert receipt["regions"]["status"] == "SOURCE_UNAVAILABLE"


def test_town_failure_removes_all_stale_temp_outputs(monkeypatch, tmp_path):
    towns = tmp_path / "towns.json"
    status = tmp_path / "status.json"
    manifest = tmp_path / "manifest.json"
    for path in (towns, status, manifest):
        path.write_text("stale", encoding="utf-8")

    def _raise(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            fetch_luma_live.TOWNS_URL,
            403,
            "Forbidden",
            {},
            None,
        )

    monkeypatch.setattr(fetch_luma_live.urllib.request, "urlopen", _raise)
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
            "--manifest-out",
            str(manifest),
        ],
    )

    assert fetch_luma_live.main() == fetch_luma_live.EXIT_SOURCE_UNAVAILABLE
    assert not towns.exists()
    assert not status.exists()
    assert not manifest.exists()


def test_receipt_bound_ingest_rejects_source_byte_mismatch(tmp_path, monkeypatch):
    src = tmp_path / "regions.json"
    meta = tmp_path / "manifest.json"
    out = tmp_path / "history.jsonl"
    src.write_bytes(b'{"raw":true}')
    meta.write_text(
        json.dumps(
            {
                "regions": {
                    "status": "PASS",
                    "url": fetch_luma_live.REGIONS_URL,
                    "retrieval_utc": "2026-09-19T12:00:00Z",
                    "response_sha256": "0" * 64,
                    "response_bytes": len(src.read_bytes()),
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_luma_status.py",
            "--src",
            str(src),
            "--snapshot-meta",
            str(meta),
            "--out",
            str(out),
        ],
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        ingest_luma_status.main()
    assert not out.exists()


def test_receipt_bound_ingest_uses_retrieval_time_and_exact_hash(tmp_path, monkeypatch):
    src = tmp_path / "regions.json"
    meta = tmp_path / "manifest.json"
    out = tmp_path / "history.jsonl"
    raw = b'{"anything":[1,2,3]}'
    src.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    meta.write_text(
        json.dumps(
            {
                "regions": {
                    "status": "PASS",
                    "url": fetch_luma_live.REGIONS_URL,
                    "retrieval_utc": "2026-09-19T12:00:00Z",
                    "response_sha256": digest,
                    "response_bytes": len(raw),
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_luma_status.py",
            "--src",
            str(src),
            "--snapshot-meta",
            str(meta),
            "--out",
            str(out),
        ],
    )

    assert ingest_luma_status.main() == 0
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["snapshot_ts"] == "2026-09-19T12:00:00Z"
    assert row["source_byte_sha256"] == digest
    assert row["source_byte_count"] == len(raw)
    assert row["schema_state"] == "RAW_UNFROZEN"
