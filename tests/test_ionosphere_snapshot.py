"""Actual immutable CI capture regression, distinct from synthetic contract tests."""

import hashlib
import json
import zipfile
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from server.backend.ionosphere_api import router

from aguayluz.ionosphere_snapshot import ARCHIVE, ARCHIVE_SHA256, SOURCE_SHA256, snapshot_context


def test_real_capture_grid_and_full_row_conservation():
    result = snapshot_context(now=datetime(2026, 10, 23, 18, tzinfo=timezone.utc))
    assert result["freshness"] == "STALE"
    assert result["selected_count"] == 6
    assert result["excluded_count"] == 5178
    assert result["selected_count"] + result["excluded_count"] == result["total_features"] == 5184
    assert result["operational_use_allowed"] is False
    assert result["spatial_binding"] == "CANDIDATE_NOT_IDENTITY"
    assert result["impact"] == "UNKNOWN"
    assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == ARCHIVE_SHA256
    with zipfile.ZipFile(ARCHIVE) as archive:
        original = json.loads(archive.read(SOURCE_SHA256 + ".bin"))
    for row in result["rows"]:
        assert row["raw_feature"] == original["features"][row["source_feature_index"]]
        assert row["raw_feature"]["properties"]["quality_flag"] == 5
    assert (-67.5, 18.75) in {(r["longitude"], r["latitude"]) for r in result["rows"]}


def test_tampered_archive_and_bad_clock_rejected(tmp_path):
    changed = tmp_path / "tampered.zip"
    changed.write_bytes(ARCHIVE.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="digest"):
        snapshot_context(changed)
    with pytest.raises(ValueError, match="clock"):
        snapshot_context(now=datetime(2026, 10, 23))
    with pytest.raises(ValueError, match="timing"):
        snapshot_context(now=datetime(2026, 10, 23, 16, tzinfo=timezone.utc))


def test_real_capture_through_api_and_failure_visibility(monkeypatch):
    monkeypatch.setenv("AGUAYLUZ_IONOSPHERE_PREVIEW", "1")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    result = client.get("/ionosphere/status").json()
    assert result["tec"]["state"] == "ARCHIVED_SNAPSHOT"
    assert result["archive"]["source_sha256"] == SOURCE_SHA256
    assert result["claims"]["live_integration"] is False
    monkeypatch.setattr(
        "server.backend.ionosphere_api.snapshot_context",
        lambda: (_ for _ in ()).throw(ValueError("digest mismatch")),
    )
    result = client.get("/ionosphere/status").json()
    assert result["archive"] == {"state": "BLOCKED", "error": "digest mismatch"}
