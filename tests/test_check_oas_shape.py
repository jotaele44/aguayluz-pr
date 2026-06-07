"""Tests for `scripts/check_oas_shape.py` — OAS shape drift detector."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_oas_shape  # type: ignore[import-not-found]  # noqa: E402


def _minimal_oas() -> dict:
    """A small but realistic OAS document with both response-shapes EPA uses."""
    return {
        "openapi": "3.0.3",
        "info": {"version": "0.1.0"},
        "servers": [{"url": "https://api.epa.gov/waters"}],
        "paths": {
            "/v1/pointindexing": {
                "get": {"responses": {"200": {"$ref": "#/components/responses/x414"}}},
                "post": {"responses": {"200": {"$ref": "#/components/responses/x414"}}},
            },
            "/v3/drainageareadelineation": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/x154"},
                                }
                            }
                        }
                    }
                }
            },
        },
    }


# ---------- shape extraction ----------


def test_extracts_response_ref_on_response_object():
    shape = check_oas_shape.compute_shape(_minimal_oas())
    assert shape["paths"]["/v1/pointindexing"]["get"] == "#/components/responses/x414"
    assert shape["paths"]["/v1/pointindexing"]["post"] == "#/components/responses/x414"


def test_extracts_response_ref_on_inner_schema():
    """The fallback path: $ref lives inside content.application/json.schema."""
    shape = check_oas_shape.compute_shape(_minimal_oas())
    assert shape["paths"]["/v3/drainageareadelineation"]["get"] == "#/components/schemas/x154"


def test_captures_server_url_and_info_version():
    shape = check_oas_shape.compute_shape(_minimal_oas())
    assert shape["server_url"] == "https://api.epa.gov/waters"
    assert shape["info_version"] == "0.1.0"


def test_ignores_non_http_method_keys():
    oas = _minimal_oas()
    # 'parameters' is a common path-level field that isn't a method.
    oas["paths"]["/v1/pointindexing"]["parameters"] = [{"name": "foo"}]
    shape = check_oas_shape.compute_shape(oas)
    assert "parameters" not in shape["paths"]["/v1/pointindexing"]


def test_handles_empty_paths():
    shape = check_oas_shape.compute_shape({"info": {}, "servers": [], "paths": {}})
    assert shape["paths"] == {}


# ---------- signature ----------


def test_signature_is_deterministic():
    s1 = check_oas_shape.shape_signature(check_oas_shape.compute_shape(_minimal_oas()))
    s2 = check_oas_shape.shape_signature(check_oas_shape.compute_shape(_minimal_oas()))
    assert s1 == s2
    assert len(s1) == 64  # sha256 hex


def test_signature_changes_when_path_added():
    base = _minimal_oas()
    s1 = check_oas_shape.shape_signature(check_oas_shape.compute_shape(base))
    base["paths"]["/v1/newpath"] = {"get": {"responses": {"200": {"$ref": "#/X"}}}}
    s2 = check_oas_shape.shape_signature(check_oas_shape.compute_shape(base))
    assert s1 != s2


def test_signature_changes_when_response_ref_changes():
    base = _minimal_oas()
    s1 = check_oas_shape.shape_signature(check_oas_shape.compute_shape(base))
    base["paths"]["/v1/pointindexing"]["get"]["responses"]["200"]["$ref"] = "#/different"
    s2 = check_oas_shape.shape_signature(check_oas_shape.compute_shape(base))
    assert s1 != s2


# ---------- diff ----------


def test_diff_empty_on_identical_shapes():
    shape = check_oas_shape.compute_shape(_minimal_oas())
    findings = check_oas_shape.diff_shapes(shape, shape)
    assert findings == []


def test_diff_reports_added_path():
    prev = check_oas_shape.compute_shape(_minimal_oas())
    after = _minimal_oas()
    after["paths"]["/v1/freshpath"] = {"get": {"responses": {"200": {"$ref": "#/Y"}}}}
    curr = check_oas_shape.compute_shape(after)
    findings = check_oas_shape.diff_shapes(prev, curr)
    assert any("path added: /v1/freshpath" in f for f in findings)


def test_diff_reports_removed_path():
    prev = check_oas_shape.compute_shape(_minimal_oas())
    after = _minimal_oas()
    del after["paths"]["/v1/pointindexing"]
    curr = check_oas_shape.compute_shape(after)
    findings = check_oas_shape.diff_shapes(prev, curr)
    assert any("path removed: /v1/pointindexing" in f for f in findings)


def test_diff_reports_method_added():
    prev = check_oas_shape.compute_shape(_minimal_oas())
    after = _minimal_oas()
    after["paths"]["/v3/drainageareadelineation"]["put"] = {
        "responses": {"200": {"$ref": "#/Z"}}
    }
    curr = check_oas_shape.compute_shape(after)
    findings = check_oas_shape.diff_shapes(prev, curr)
    assert any("method added: put" in f for f in findings)


def test_diff_reports_response_shape_change():
    prev = check_oas_shape.compute_shape(_minimal_oas())
    after = _minimal_oas()
    after["paths"]["/v1/pointindexing"]["get"]["responses"]["200"]["$ref"] = "#/components/responses/EVOLVED"
    curr = check_oas_shape.compute_shape(after)
    findings = check_oas_shape.diff_shapes(prev, curr)
    assert any("response shape changed" in f for f in findings)
    assert any("EVOLVED" in f for f in findings)


def test_diff_reports_server_url_change():
    prev_shape = check_oas_shape.compute_shape(_minimal_oas())
    after = _minimal_oas()
    after["servers"][0]["url"] = "https://api.epa.gov/waters-v2"
    curr_shape = check_oas_shape.compute_shape(after)
    findings = check_oas_shape.diff_shapes(prev_shape, curr_shape)
    assert any("server_url changed" in f for f in findings)


# ---------- CLI ----------


def test_cli_check_passes_against_self(tmp_path):
    """--write-snapshot then --check on the same input yields exit 0."""
    oas_file = tmp_path / "oas.json"
    oas_file.write_text(json.dumps(_minimal_oas()), encoding="utf-8")
    snap = tmp_path / "shape.json"

    rc = check_oas_shape.main([
        "--write-snapshot",
        "--from-file", str(oas_file),
        "--snapshot-path", str(snap),
    ])
    assert rc == 0
    assert snap.exists()

    rc = check_oas_shape.main([
        "--check",
        "--from-file", str(oas_file),
        "--snapshot-path", str(snap),
    ])
    assert rc == 0


def test_cli_check_fails_on_drift(tmp_path):
    base_file = tmp_path / "base.json"
    base_file.write_text(json.dumps(_minimal_oas()), encoding="utf-8")
    snap = tmp_path / "shape.json"

    check_oas_shape.main([
        "--write-snapshot",
        "--from-file", str(base_file),
        "--snapshot-path", str(snap),
    ])

    drifted = _minimal_oas()
    drifted["paths"]["/v1/newendpoint"] = {"get": {"responses": {"200": {"$ref": "#/N"}}}}
    drifted_file = tmp_path / "drifted.json"
    drifted_file.write_text(json.dumps(drifted), encoding="utf-8")

    rc = check_oas_shape.main([
        "--check",
        "--from-file", str(drifted_file),
        "--snapshot-path", str(snap),
    ])
    assert rc == 1


def test_cli_check_returns_2_when_snapshot_missing(tmp_path):
    oas_file = tmp_path / "oas.json"
    oas_file.write_text(json.dumps(_minimal_oas()), encoding="utf-8")
    rc = check_oas_shape.main([
        "--check",
        "--from-file", str(oas_file),
        "--snapshot-path", str(tmp_path / "nope.json"),
    ])
    assert rc == 2


def test_committed_snapshot_matches_live_signature():
    """Drift guard for the committed snapshot itself: the file must parse and
    its `shape_signature` must match a fresh signature() over its `shape`."""
    snapshot = json.loads(
        (REPO_ROOT / "tests" / "baseline" / "waters_oas_shape.json").read_text(encoding="utf-8")
    )
    expected = check_oas_shape.shape_signature(snapshot["shape"])
    assert snapshot["shape_signature"] == expected
