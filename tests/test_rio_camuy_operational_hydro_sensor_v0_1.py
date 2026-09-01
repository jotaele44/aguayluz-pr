from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from server.backend.app import app  # noqa: E402
from server.backend.cave_karst_api import evaluate_replay_sample  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "rio_camuy_operational_hydro_sensor_v0_1.json"
PUBLIC_PATH = ROOT / "data" / "rio_camuy_monitoring_public_v0_1.json"
REPLAY_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "rio_camuy_operational_hydro_sensor_v0_1"
    / "replay_cases.json"
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_modern_usgs_contract_and_zero_retired_sensorthings_dependency() -> None:
    config = load_json(CONFIG_PATH)
    modern = config["modern_usgs"]

    assert modern["root"] == "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
    assert modern["current_collection"] == "latest-continuous"
    assert modern["history_collection"] == "continuous"
    assert modern["monitoring_locations_collection"] == "monitoring-locations"
    assert modern["time_series_metadata_collection"] == "time-series-metadata"
    assert modern["retired_sensor_things_dependency"] is False
    assert config["policy"]["sensor_things_enabled"] is False
    assert "sensorthings" not in json.dumps(config).lower()


def test_source_bound_crosswalk_is_complete_and_fail_closed() -> None:
    config = load_json(CONFIG_PATH)
    required_source = {"source_id", "provider", "privacy_class", "provenance"}
    required_stream = {
        "observed_property",
        "unit",
        "datum",
        "quality_flag_source",
        "sampling_cadence",
    }

    assert config["sources"]
    for source in config["sources"]:
        assert required_source <= source.keys()
        assert source["source_id"].startswith("SRC_KARST_")
        assert source["privacy_class"] in {
            "P0_PUBLIC",
            "P1_GENERALIZED",
            "P2_CONTROLLED",
            "P3_RESTRICTED",
        }
        for stream in source.get("datastreams", [source]):
            assert required_stream <= stream.keys()

    by_id = {source["source_id"]: source for source in config["sources"]}
    current = by_id["SRC_KARST_USGS_50014800"]
    historical = by_id["SRC_KARST_USGS_50014600"]

    assert current["current_operational_admission"] is True
    assert {row["parameter_code"] for row in current["datastreams"]} >= {
        "00060",
        "00065",
        "72365",
    }
    precipitation = next(row for row in current["datastreams"] if row["parameter_code"] == "00045")
    assert precipitation["current_operational_admission"] is False
    assert historical["current_operational_admission"] is False
    assert historical["datastreams"][0]["parameter_code"] == "00060"


def test_uncommissioned_local_sensor_contracts_never_become_operational_truth() -> None:
    config = load_json(CONFIG_PATH)
    local = [source for source in config["sources"] if source["privacy_class"] in {"P2_CONTROLLED", "P3_RESTRICTED"}]

    assert len(local) == 6
    assert all(source["commissioned"] is False for source in local)
    assert all(source["current_operational_admission"] is False for source in local)
    assert config["policy"]["live_polling_scheduled"] is False
    assert config["policy"]["public_notifications_enabled"] is False
    assert config["policy"]["automatic_public_reopening_enabled"] is False


def test_stage_and_rain_thresholds_remain_pilot_provisional() -> None:
    config = load_json(CONFIG_PATH)
    thresholds = config["pilot_thresholds"]

    for key in ("stage_rise_15m_m", "stage_rise_30m_m", "rain_1h_mm", "rain_3h_mm"):
        assert thresholds[key]["authority"] == "pilot_provisional"
        assert thresholds[key]["operational_authority"] is False

    assert config["policy"]["stage_rain_thresholds_authority"] == "pilot_provisional"
    assert config["policy"]["stage_rain_operational_authority"] is False
    assert set(config["activation_gates"]) >= {
        "surveyed_camuy_stage_elevations",
        "hydraulic_response_characterization",
        "operator_evacuation_time_study",
    }


def test_offline_replay_matrix_has_zero_missed_severity_five_conditions() -> None:
    fixture = load_json(REPLAY_PATH)
    cases = fixture["cases"]
    assert {case["case_id"] for case in cases} == {
        "normal",
        "stale",
        "rapid_stage_rise",
        "rainfall_precursor",
        "oxygen_deficiency",
        "co2_elevation",
        "co2_critical",
        "sensor_loss",
        "comms_loss",
        "blocked_egress",
    }

    for case in cases:
        alerts = evaluate_replay_sample(case["sample"])
        alert_types = {item["alert_type"] for item in alerts}
        assert alert_types == set(case["expected_alert_types"])
        if case["severity_5_required"]:
            assert any(item["severity"] == 5 for item in alerts)
        actions = " ".join(str(item["action"]).lower() for item in alerts)
        assert "safe" not in actions
        assert "reopen" not in actions
        assert "open_access" not in actions


def test_missing_stale_and_comms_loss_never_infer_safe_state() -> None:
    for sample in (
        {},
        {"sensor_heartbeats_missed": 2, "stale": True},
        {"sensor_heartbeats_missed": 2, "communications_lost": True},
    ):
        alerts = evaluate_replay_sample(sample)
        assert not any(
            token in str(item["action"]).lower()
            for item in alerts
            for token in ("safe", "reopen", "open_access")
        )


def test_public_monitoring_projection_contains_only_p0_identifiable_sources() -> None:
    public = load_json(PUBLIC_PATH)

    assert public["projection_mode"] == "read_only"
    assert public["operational_status_authority"] is False
    assert public["public_notifications_enabled"] is False
    assert public["automatic_public_reopening_enabled"] is False
    assert public["modern_usgs"]["retired_sensor_things_dependency"] is False
    assert public["public_sources"]
    assert all(source["privacy_class"] == "P0_PUBLIC" for source in public["public_sources"])
    assert {source["site_number"] for source in public["public_sources"]} == {
        "50014800",
        "50014600",
    }

    restricted = public["restricted_contracts"]
    assert restricted == {
        "count": 6,
        "identifiers_exposed": False,
        "sensor_identifiers_exposed": False,
        "monitoring_site_identifiers_exposed": False,
        "emergency_geometry_exposed": False,
        "commissioned_sensor_count": 0,
        "message": restricted["message"],
    }

    serialized = json.dumps(public)
    config = load_json(CONFIG_PATH)
    for source in config["sources"]:
        if source["privacy_class"] in {"P2_CONTROLLED", "P3_RESTRICTED"}:
            source_id = source["source_id"]
            assert source_id not in serialized


def test_current_camuy_closed_state_and_cave_surface_remain_get_only() -> None:
    with TestClient(app) as client:
        park = client.get("/cave-karst/assets/AYL_KARST_CAMUY_PARK")
        assert park.status_code == 200
        body = park.json()
        assert body["current_status"] == "closed"
        assert body["coordinates_redacted"] is True

        cave_paths = {
            path: methods
            for path, methods in app.openapi()["paths"].items()
            if path.startswith("/cave-karst")
        }
        assert cave_paths
        assert {method for methods in cave_paths.values() for method in methods} == {"get"}
        post_response = client.post("/cave-karst/summary")
        patch_response = client.patch("/cave-karst/assets/AYL_KARST_CAMUY_PARK")
        delete_response = client.delete("/cave-karst/alerts")
        assert post_response.status_code == 405
        assert patch_response.status_code == 405
        assert delete_response.status_code == 405
