"""server/backend/main._load_jsonl / _load_json cache: hits on unchanged mtime,
misses once the file's mtime moves.

The dashboard polls /health every 15s and /system/status every 30s
(dashboard/src/lib/hooks.js), each of which re-parsed several JSONL corpora
from disk on every single request even though those files only change when
the cron refresh job commits new data. This is the regression test for that
cache (server/backend/main.py:_load_jsonl / _load_json).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("fastapi")

import server.backend.main as backend  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    backend._file_cache.clear()
    yield
    backend._file_cache.clear()


def _count_read_text_calls(monkeypatch):
    calls = {"n": 0}
    original = Path.read_text

    def _wrapped(self, *args, **kwargs):
        calls["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _wrapped)
    return calls


def _bump_mtime(path: Path) -> None:
    """Advance the file's mtime by 1s, independent of filesystem clock resolution."""
    current_ns = path.stat().st_mtime_ns
    new_ns = current_ns + 1_000_000_000
    os.utime(path, ns=(new_ns, new_ns))


def test_load_jsonl_cache_hit_on_unchanged_file(tmp_path, monkeypatch):
    p = tmp_path / "rows.jsonl"
    p.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    calls = _count_read_text_calls(monkeypatch)

    first = backend._load_jsonl(p)
    second = backend._load_jsonl(p)

    assert first == [{"a": 1}, {"a": 2}]
    assert second is first  # same cached object returned, not merely equal
    assert calls["n"] == 1


def test_load_jsonl_cache_miss_after_mtime_change(tmp_path, monkeypatch):
    p = tmp_path / "rows.jsonl"
    p.write_text('{"a": 1}\n', encoding="utf-8")
    calls = _count_read_text_calls(monkeypatch)

    first = backend._load_jsonl(p)
    p.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    _bump_mtime(p)
    second = backend._load_jsonl(p)

    assert first == [{"a": 1}]
    assert second == [{"a": 1}, {"a": 2}]
    assert calls["n"] == 2


def test_load_jsonl_missing_file_evicts_cache(tmp_path):
    p = tmp_path / "rows.jsonl"
    p.write_text('{"a": 1}\n', encoding="utf-8")
    backend._load_jsonl(p)
    assert p in backend._file_cache

    p.unlink()
    assert backend._load_jsonl(p) == []
    assert p not in backend._file_cache


def test_load_json_cache_hit_on_unchanged_file(tmp_path, monkeypatch):
    p = tmp_path / "doc.json"
    p.write_text(json.dumps({"x": 1}), encoding="utf-8")
    calls = _count_read_text_calls(monkeypatch)

    first = backend._load_json(p)
    second = backend._load_json(p)

    assert first == {"x": 1}
    assert second is first
    assert calls["n"] == 1


def test_load_json_cache_miss_after_mtime_change(tmp_path):
    p = tmp_path / "doc.json"
    p.write_text(json.dumps({"x": 1}), encoding="utf-8")

    first = backend._load_json(p)
    p.write_text(json.dumps({"x": 2}), encoding="utf-8")
    _bump_mtime(p)
    second = backend._load_json(p)

    assert first == {"x": 1}
    assert second == {"x": 2}
