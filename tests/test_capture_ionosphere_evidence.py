"""Synthetic transport regression, separate from actual NOAA evidence."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ionosphere_capture",
    Path(__file__).resolve().parents[1] / "scripts/capture_ionosphere_evidence.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_http_failure_is_not_empty_measurements(tmp_path):
    result = MODULE.capture(tmp_path, lambda url: (403, b"denied"))
    assert result["state"] == "BLOCKED"
    assert result["measurement_count"] is None
    assert (tmp_path / (result["attempts"][0]["sha256"] + ".bin")).read_bytes() == b"denied"


def test_capture_inventory_does_not_certify_geometry(tmp_path):
    raw = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {"tec": None}, "geometry": None}],
        }
    ).encode()

    def fetch(url):
        return (200, b"glotec_icao_20261023T000000Z.geojson") if url == MODULE.BASE else (200, raw)

    result = MODULE.capture(tmp_path, fetch)
    assert result["state"] == "ACQUIRED_UNVERIFIED"
    assert result["schema_inventory"]["feature_count"] == 1
    assert result["schema_inventory"]["null_geometries"] == 1
    assert result["geographic_certification"] == "UNRESOLVED"


def test_invalid_payload_and_replay(tmp_path):
    for raw in (b"<html>error</html>", b'{"type":"FeatureCollection","features":[]}'):
        with pytest.raises(ValueError):
            MODULE.inspect_capture(raw)
    digest = MODULE.freeze(tmp_path, b"raw source")
    assert MODULE.freeze(tmp_path, b"raw source") == digest
    (tmp_path / (digest + ".bin")).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="collision"):
        MODULE.freeze(tmp_path, b"raw source")


def test_listing_failure_and_bad_feature(tmp_path):
    result = MODULE.capture(tmp_path, lambda url: (200, b"no files"))
    assert result["state"] == "BLOCKED"
    assert len(result["attempts"]) == 1
    with pytest.raises(ValueError):
        MODULE.inspect_capture(b'{"type":"FeatureCollection","features":[null]}')
