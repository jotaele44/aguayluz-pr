from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "rio_camuy_usgs_snapshot_v0_2" / "http_cases.json"
CONFIG = REPO / "config" / "rio_camuy_usgs_snapshot_v0_2.json"
_SPEC = importlib.util.spec_from_file_location("rio_camuy_usgs_snapshot", REPO / "tools" / "rio_camuy_usgs_snapshot.py")
assert _SPEC and _SPEC.loader
snapshot = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = snapshot
_SPEC.loader.exec_module(snapshot)


def _fixtures() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _response(case: dict, request: httpx.Request) -> httpx.Response:
    return httpx.Response(case["status"], json=case["document"], request=request)


def _receipt_for(case_name: str = "valid"):
    case = _fixtures()["cases"][case_name]
    request = httpx.Request("GET", f"{snapshot.ROOT}/latest-continuous/items")
    return snapshot._receipt(_response(case, request), "2026-08-08T22:30:00Z")


def test_contract_is_operator_only_env_keyed_and_fail_closed():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert config["operator_invoked_only"] is True
    assert config["scheduler_enabled"] is False
    assert config["public_notifications_enabled"] is False
    assert config["automatic_public_reopening_enabled"] is False
    assert config["retired_sensor_things_dependency"] is False
    assert config["credential"] == {
        "environment_variable": "USGS_API_KEY", "transport": "X-Api-Key header", "required": True,
        "persisted": False, "query_parameter_allowed": False,
    }
    assert config["local_sensor_boundary"]["commissioned_count"] == 0
    assert config["threshold_boundary"]["stage_rain_authority"] == "pilot_provisional"
    assert config["threshold_boundary"]["operational_authority"] is False
    assert config["fail_closed"]["safe_open_reopen_actions_allowed"] is False


def test_adapter_has_no_cli_api_key_or_scheduler_surface():
    source = (REPO / "tools" / "rio_camuy_usgs_snapshot.py").read_text(encoding="utf-8")
    assert 'os.environ.get("USGS_API_KEY"' in source
    assert '"X-Api-Key": api_key' in source
    assert "--api-key" not in source
    assert "apscheduler" not in source.lower()
    assert "cron" not in source.lower()
    assert "sensorthings" not in source.lower()


def test_valid_observation_normalizes_required_fields_and_receipt_hash():
    feature = _fixtures()["cases"]["valid"]["document"]["features"][0]
    row = snapshot.normalize_observation(feature, _receipt_for(), collection="latest-continuous", now=datetime(2026, 8, 8, 22, 30, tzinfo=timezone.utc))
    assert row is not None
    required = {
        "source_id", "monitoring_location", "parameter_code", "observed_property", "value", "unit", "datum",
        "observed_at", "qualifier", "approval_status", "received_at", "request_receipt_sha256", "evidence_tier",
        "quality_flag", "privacy_class", "operational_admission",
    }
    assert required <= set(row)
    assert row["source_id"] == "SRC_KARST_USGS_50014800"
    assert row["parameter_code"] == "00060"
    assert row["observed_property"] == "discharge"
    assert row["evidence_tier"] == "T1"
    assert row["privacy_class"] == "P0_PUBLIC"
    assert row["quality_flag"] == "validated"
    assert row["freshness"] == "current"
    assert row["operational_admission"] is True
    assert len(row["request_receipt_sha256"]) == 64
    int(row["request_receipt_sha256"], 16)


def test_stale_current_observation_is_not_fresh():
    feature = _fixtures()["cases"]["stale"]["document"]["features"][0]
    row = snapshot.normalize_observation(feature, _receipt_for("stale"), collection="latest-continuous", now=datetime(2026, 8, 8, 22, 30, tzinfo=timezone.utc))
    assert row is not None
    assert row["freshness"] == "stale"
    assert row["operational_admission"] is True


def test_partial_observation_is_not_promoted():
    feature = _fixtures()["cases"]["partial"]["document"]["features"][0]
    assert snapshot.normalize_observation(feature, _receipt_for("partial"), collection="latest-continuous") is None


def test_50014600_and_50014800_precipitation_are_historical_only():
    receipt = _receipt_for()
    historical_site = {"properties": {"monitoring_location_id": "USGS-50014600", "parameter_code": "00060", "value": 12.0, "unit_of_measure": "ft3/s", "time": "1996-01-01T00:00:00Z"}}
    historical_rain = {"properties": {"monitoring_location_id": "USGS-50014800", "parameter_code": "00045", "value": 0.2, "unit_of_measure": "in", "time": "2022-01-01T00:00:00Z"}}
    assert snapshot.normalize_observation(historical_site, receipt, collection="continuous")["operational_admission"] is False
    assert snapshot.normalize_observation(historical_rain, receipt, collection="continuous")["operational_admission"] is False


@pytest.mark.parametrize(("case_name", "expected_code"), [("rate_limited", "rate_limited"), ("upstream_5xx", "upstream_5xx"), ("schema_drift", "schema_drift")])
def test_http_failures_are_classified(case_name: str, expected_code: str):
    case = _fixtures()["cases"][case_name]

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(case, request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.fetch_collection(client, "latest-continuous", site="50014800", parameter_code="00060")
    assert exc.value.code == expected_code


def test_empty_response_is_explicitly_missing_and_never_safe():
    case = _fixtures()["cases"]["empty"]

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(case, request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows, receipts = snapshot.fetch_collection(client, "latest-continuous", site="50014800", parameter_code="00060")
    assert rows == []
    assert len(receipts) == 1

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = snapshot.materialize_snapshot(client, now=datetime(2026, 8, 8, 22, 30, tzinfo=timezone.utc))
    assert result["operational_state"] == "unknown"
    assert result["safe_open_reopen_inference"] is False
    assert result["diagnostics"]
    assert {item["code"] for item in result["diagnostics"]} == {"empty_response"}


def test_pagination_follows_next_link_and_hashes_each_page():
    cases = _fixtures()["cases"]

    def handler(request: httpx.Request) -> httpx.Response:
        name = "paginated_second" if request.url.params.get("cursor") == "page2" else "paginated_first"
        return _response(cases[name], request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows, receipts = snapshot.fetch_collection(client, "latest-continuous", site="50014800", parameter_code="00060")
    assert len(rows) == 2
    assert len(receipts) == 2
    assert receipts[0].request_receipt_sha256 != receipts[1].request_receipt_sha256


@pytest.mark.parametrize(("case_name", "expected_code"), [("unknown_parameter", "unknown_parameter"), ("out_of_scope_site", "out_of_scope_site")])
def test_unknown_parameter_and_out_of_scope_site_are_rejected(case_name: str, expected_code: str):
    feature = _fixtures()["cases"][case_name]["document"]["features"][0]
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.normalize_observation(feature, _receipt_for(), collection="latest-continuous")
    assert exc.value.code == expected_code


def test_failed_snapshot_degrades_to_unknown_and_never_access_action():
    case = _fixtures()["cases"]["rate_limited"]

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(case, request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = snapshot.materialize_snapshot(client, now=datetime(2026, 8, 8, 22, 30, tzinfo=timezone.utc))
    assert result["operational_state"] == "unknown"
    assert result["safe_open_reopen_inference"] is False
    assert result["public_notifications_enabled"] is False
    assert result["automatic_public_reopening_enabled"] is False
    assert result["diagnostics"]


def test_internal_projection_is_p0_only_and_contains_no_emergency_geometry():
    synthetic = {
        "schema_version": "aguayluz.rio-camuy-usgs-snapshot/v0.2", "generated_at": "2026-08-08T22:30:00Z",
        "operational_state": "unknown", "observations": [
            {"source_id": "SRC_KARST_USGS_50014800", "privacy_class": "P0_PUBLIC"},
            {"source_id": "LOCAL_SECRET", "privacy_class": "P3_RESTRICTED", "sensor_id": "secret"},
        ], "diagnostics": [], "emergency_geometry": {"route": "restricted"},
    }
    projected = snapshot.internal_projection(synthetic)
    assert [row["source_id"] for row in projected["observations"]] == ["SRC_KARST_USGS_50014800"]
    assert "emergency_geometry" not in projected
    assert "sensor_id" not in json.dumps(projected)
    assert projected["local_sensor_commissioned_count"] == 0
    assert projected["stage_rain_thresholds_authority"] == "pilot_provisional"


def test_existing_cave_karst_surface_remains_get_only_and_camuy_closed():
    api_source = (REPO / "server" / "backend" / "cave_karst_api.py").read_text(encoding="utf-8")
    assert "@router.post(" not in api_source
    assert "@router.patch(" not in api_source
    assert "@router.delete(" not in api_source
    assets = [json.loads(line) for line in (REPO / "data" / "cave_karst_assets.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    park = next(item for item in assets if item["asset_id"] == "AYL_KARST_CAMUY_PARK")
    assert park["operational"]["status"] == "closed"
    assert park["operational"]["public_access"] == "no"
