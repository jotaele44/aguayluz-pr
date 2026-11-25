"""GET /events/stream must reflect current data, not the frozen startup snapshot.

Regression test: the SSE generator used to close over the module-level
``_events`` list, built once at import time (server/backend/main.py comment:
"restart server to pick up data changes"), so the "live" stream just replayed
whatever was on disk when the process started. It now calls
``_current_events()``, which re-reads from disk each tick.

Calls the route function directly (via ``asyncio.run``) rather than through
TestClient/HTTP: the generator's ``while True: ... await asyncio.sleep(5)``
never completes, and driving it through a real streaming HTTP client in this
test environment hangs waiting for the connection to close. A minimal
duck-typed ``Request`` stub (the route only calls ``is_disconnected()``) gets
one chunk out of the underlying ``StreamingResponse.body_iterator`` instead.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("fastapi")

import server.backend.main as backend  # noqa: E402


class _FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


def _first_sse_payload() -> list:
    async def _run():
        response = await backend.events_stream(_FakeRequest())
        chunk = await response.body_iterator.__anext__()
        return chunk

    chunk = asyncio.run(_run())
    text = chunk.decode() if isinstance(chunk, bytes) else chunk
    assert text.startswith("data: ")
    return json.loads(text[len("data: "):])


def test_stream_reflects_current_events_not_stale_snapshot(monkeypatch):
    """The endpoint must read ``_current_events()``, not the frozen ``_events``."""
    stale = [{"event_id": "STALE", "start_time": "2020-01-01T00:00:00+00:00"}]
    fresh = [{"event_id": "FRESH", "start_time": "2026-01-01T00:00:00+00:00"}]
    monkeypatch.setattr(backend, "_events", stale)
    monkeypatch.setattr(backend, "_current_events", lambda: fresh)

    assert _first_sse_payload() == fresh


def test_current_events_picks_up_a_newly_written_row(tmp_path, monkeypatch):
    """Direct unit test of _current_events(): a row appended after import-time
    must appear on the next call, which is exactly what the frozen ``_events``
    snapshot could never do without a server restart."""
    service_events = tmp_path / "service_events.jsonl"
    aee_incidents = tmp_path / "aee_incidents.jsonl"
    live_incidents = tmp_path / "luma_live_incidents.jsonl"
    service_events.write_text("", encoding="utf-8")
    aee_incidents.write_text("", encoding="utf-8")
    live_incidents.write_text("", encoding="utf-8")

    backend._file_cache.clear()
    monkeypatch.setattr(backend, "_EVENT_SOURCE_PATHS", (service_events, aee_incidents))
    monkeypatch.setattr(backend, "_live_event_path", live_incidents)

    assert backend._current_events() == []

    service_events.write_text(json.dumps({"event_id": "NEW_ROW"}) + "\n", encoding="utf-8")
    assert backend._current_events() == [{"event_id": "NEW_ROW"}]
