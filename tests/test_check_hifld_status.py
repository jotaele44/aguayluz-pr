"""Tests for `scripts/check_hifld_status.py`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_hifld_status  # type: ignore[import-not-found]  # noqa: E402


def _obs(status: str, **kw) -> dict:  # type: ignore[no-untyped-def]
    base = {
        "status": status,
        "feature_count": kw.pop("feature_count", 0),
        "url": kw.pop("url", "https://example/query"),
        "observed_at": "2026-06-06T12:00:00Z",
    }
    base.update(kw)
    return base


# ---------- _probe_layer ----------


def test_probe_live_url_returns_live(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        json={"type": "FeatureCollection", "features": [{"id": 1}, {"id": 2}]},
        status_code=200,
    )
    result = check_hifld_status._probe_layer(url="https://example/q")
    assert result["status"] == "live"
    assert result["feature_count"] == 2


def test_probe_empty_feature_list_returns_empty(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        json={"type": "FeatureCollection", "features": []},
        status_code=200,
    )
    result = check_hifld_status._probe_layer(url="https://example/q")
    assert result["status"] == "empty"
    assert result["feature_count"] == 0


def test_probe_arcgis_error_body_returns_service_error(httpx_mock):
    """ArcGIS habit: HTTP 200 with `{error: …}` body when URL path is wrong."""
    httpx_mock.add_response(
        method="GET",
        json={"error": {"code": 400, "message": "Invalid URL"}},
        status_code=200,
    )
    result = check_hifld_status._probe_layer(url="https://example/q")
    assert result["status"] == "service_error"
    assert "Invalid URL" in result["error"]


def test_probe_http_400_returns_down(httpx_mock):
    httpx_mock.add_response(method="GET", status_code=400, text="bad")
    result = check_hifld_status._probe_layer(url="https://example/q")
    assert result["status"] == "down"
    assert "HTTP 400" in result["error"]


def test_probe_non_json_200_returns_down(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        content=b"<html>not json</html>",
        status_code=200,
    )
    result = check_hifld_status._probe_layer(url="https://example/q")
    assert result["status"] == "down"


def test_probe_unexpected_shape_returns_down(httpx_mock):
    """200 + valid JSON but not a FeatureCollection."""
    httpx_mock.add_response(method="GET", json={"type": "Feature"}, status_code=200)
    result = check_hifld_status._probe_layer(url="https://example/q")
    assert result["status"] == "down"
    assert "unexpected" in result["error"]


def test_probe_network_failure_returns_down(httpx_mock):
    """httpx exception (timeout/DNS) routes to down with a network reason."""
    import httpx
    httpx_mock.add_exception(httpx.ConnectError("dns failed"))
    result = check_hifld_status._probe_layer(url="https://example/q")
    assert result["status"] == "down"
    assert "network" in result["error"]


# ---------- diff_observations ----------


def test_diff_no_transitions_is_empty():
    baseline = {"l1": _obs("live", feature_count=10)}
    current = {"l1": _obs("live", feature_count=10)}
    assert check_hifld_status.diff_observations(baseline, current) == []


def test_diff_live_to_down_is_critical():
    baseline = {"l1": _obs("live", feature_count=10)}
    current = {"l1": _obs("down", error="HTTP 500")}
    findings = check_hifld_status.diff_observations(baseline, current)
    assert len(findings) == 1
    assert findings[0]["kind"] == "went_down"
    assert findings[0]["severity"] == "critical"


def test_diff_live_to_service_error_is_critical():
    baseline = {"l1": _obs("live", feature_count=10)}
    current = {"l1": _obs("service_error", error="Invalid URL")}
    findings = check_hifld_status.diff_observations(baseline, current)
    assert findings[0]["kind"] == "went_down"
    assert findings[0]["severity"] == "critical"


def test_diff_down_to_live_is_info_with_refresh_hint():
    baseline = {"l1": _obs("down", error="HTTP 400")}
    current = {"l1": _obs("live", feature_count=42)}
    findings = check_hifld_status.diff_observations(baseline, current)
    assert findings[0]["kind"] == "came_back"
    assert findings[0]["severity"] == "info"
    assert "--refresh-snapshot l1" in findings[0]["message"]


def test_diff_service_error_to_live_also_info():
    """Coming back from any non-live state should fire 'came_back'."""
    baseline = {"l1": _obs("service_error", error="x")}
    current = {"l1": _obs("live", feature_count=5)}
    findings = check_hifld_status.diff_observations(baseline, current)
    assert findings[0]["kind"] == "came_back"


def test_diff_feature_count_drift_above_25pct_is_warn():
    baseline = {"l1": _obs("live", feature_count=100)}
    current = {"l1": _obs("live", feature_count=200)}
    findings = check_hifld_status.diff_observations(baseline, current)
    assert findings[0]["kind"] == "count_drift"
    assert findings[0]["severity"] == "warn"
    assert findings[0]["prev_count"] == 100
    assert findings[0]["curr_count"] == 200


def test_diff_feature_count_drift_below_25pct_is_silent():
    """20% movement is dataset noise — should not fire."""
    baseline = {"l1": _obs("live", feature_count=100)}
    current = {"l1": _obs("live", feature_count=120)}
    findings = check_hifld_status.diff_observations(baseline, current)
    assert findings == []


def test_diff_new_layer_emits_info():
    baseline = {}
    current = {"l2": _obs("down")}
    findings = check_hifld_status.diff_observations(baseline, current)
    assert findings[0]["kind"] == "new"
    assert findings[0]["severity"] == "info"


def test_diff_removed_layer_emits_warn():
    baseline = {"l1": _obs("live", feature_count=10)}
    current = {}
    findings = check_hifld_status.diff_observations(baseline, current)
    assert findings[0]["kind"] == "removed"
    assert findings[0]["severity"] == "warn"


def test_diff_stable_down_state_silent():
    """down → down (or any unchanged non-live state) shouldn't alert."""
    baseline = {"l1": _obs("down")}
    current = {"l1": _obs("down")}
    assert check_hifld_status.diff_observations(baseline, current) == []


# ---------- CLI ----------


def test_cli_write_then_check_passes(tmp_path):
    """Write baseline from a synthetic observation, then --check the same input
    via --from-file → exit 0."""
    obs_file = tmp_path / "obs.json"
    obs_file.write_text(json.dumps({"l1": _obs("down")}), encoding="utf-8")
    baseline = tmp_path / "baseline.json"

    rc = check_hifld_status.main([
        "--write-baseline", "--from-file", str(obs_file),
        "--baseline-path", str(baseline),
    ])
    assert rc == 0
    assert baseline.exists()

    rc = check_hifld_status.main([
        "--check", "--from-file", str(obs_file),
        "--baseline-path", str(baseline),
    ])
    assert rc == 0


def test_cli_check_returns_2_when_baseline_missing(tmp_path):
    obs_file = tmp_path / "obs.json"
    obs_file.write_text("{}", encoding="utf-8")
    rc = check_hifld_status.main([
        "--check", "--from-file", str(obs_file),
        "--baseline-path", str(tmp_path / "absent.json"),
    ])
    assert rc == 2


def test_cli_check_returns_1_on_drift(tmp_path):
    baseline_obs = tmp_path / "baseline_obs.json"
    baseline_obs.write_text(json.dumps({"l1": _obs("live", feature_count=10)}), encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    check_hifld_status.main([
        "--write-baseline", "--from-file", str(baseline_obs),
        "--baseline-path", str(baseline),
    ])

    drifted = tmp_path / "drifted.json"
    drifted.write_text(json.dumps({"l1": _obs("down", error="HTTP 500")}), encoding="utf-8")
    rc = check_hifld_status.main([
        "--check", "--from-file", str(drifted),
        "--baseline-path", str(baseline),
    ])
    assert rc == 1


def test_committed_baseline_loads_and_has_required_keys():
    """The committed `tests/baseline/hifld_layer_status.json` parses cleanly."""
    data = json.loads(
        (REPO_ROOT / "tests" / "baseline" / "hifld_layer_status.json").read_text(encoding="utf-8")
    )
    assert "layers" in data
    for name, obs in data["layers"].items():
        assert "status" in obs, f"{name} missing status"
        assert obs["status"] in {"live", "empty", "service_error", "down"}


def test_refresh_snapshot_unknown_layer_returns_2(tmp_path):
    rc = check_hifld_status.main([
        "--refresh-snapshot", "imaginary_layer", str(tmp_path / "out.geojson"),
    ])
    assert rc == 2
