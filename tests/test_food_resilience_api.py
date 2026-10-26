import hashlib
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from server.backend import main as legacy
from server.backend.app import app
from server.backend.food_resilience_api import (
    _grid_outage_signal,
    _latest_metric,
    load_food_resilience_contract,
)

client = TestClient(app)


def test_food_state_is_phase1_and_higher_phase_metrics_are_locked():
    response = client.get('/food-resilience/state')
    assert response.status_code == 200
    state = response.json()
    assert state['vector_id'] == 'FOOD_SYSTEM_RESILIENCE'
    assert state['activation_phase'] == 1
    assert state['overall_state'] == 'UNKNOWN'
    assert state['phase1_warning_state'] in {'UNKNOWN', 'NORMAL', 'WATCH', 'ELEVATED', 'SEVERE', 'CRITICAL'}
    assert 'not a certified food-resilience score' in state['state_semantics']
    assert state['metrics']['dynamic_coverage']['value'] is None
    assert state['metrics']['dynamic_coverage']['availability_state'] == 'MODEL_UNAVAILABLE'
    assert state['metrics']['robust_coverage_p50']['value'] is None
    assert state['metrics']['robust_coverage_p50']['availability_state'] == 'MODEL_UNAVAILABLE'


def test_phase1_missing_signals_fail_closed_as_unknown():
    response = client.get('/food-resilience/phase1/signals')
    assert response.status_code == 200
    items = {item['signal_id']: item for item in response.json()['items']}
    assert items['FOOD.P1.PORT_STATUS']['state'] == 'UNKNOWN'
    assert items['FOOD.P1.PORT_STATUS']['value'] is None
    assert items['FOOD.P1.COLD_CHAIN']['state'] == 'UNKNOWN'
    assert items['FOOD.P1.COLD_CHAIN']['availability_state'] == 'UNRESOLVED'


def test_phase2_baseline_preserves_reference_period_and_is_not_current_operational_baseline():
    response = client.get('/food-resilience/baseline')
    assert response.status_code == 200
    baseline = response.json()
    assert baseline['current_operational_baseline'] is False
    records = {record['metric_id']: record for record in baseline['records']}
    assert records['A.NASS2022.FARM_COUNT']['reference_period'] == '2022'
    assert records['A.BEZARES.FSR_TOTAL']['reference_period'] == 'FY2017-FY2019'
    assert records['A.BEZARES.FSR_TOTAL']['role'] == 'HISTORICAL_VALIDATION'


def test_dependency_graph_has_no_dangling_node_references():
    response = client.get('/food-resilience/dependencies')
    assert response.status_code == 200
    graph = response.json()
    nodes = set(graph['nodes'])
    assert graph['count_nodes'] == len(nodes)
    assert graph['count_edges'] == len(graph['edges'])
    for upstream, downstream, dependency_type, sign in graph['edges']:
        assert upstream in nodes
        assert downstream in nodes
        assert dependency_type
        assert sign in (-1, 1)


def test_food_resilience_api_is_read_only():
    assert client.post('/food-resilience/state').status_code == 405
    assert client.post('/food-resilience/baseline').status_code == 405
    assert client.post('/food-resilience/scenarios').status_code == 405


def test_phase1_metric_bindings_exist_in_canonical_registry():
    expected = {
        "precipitation": {"precipitation_pct_normal"},
        "reservoir": {"streamflow", "reservoir_elevation"},
        "groundwater": {"groundwater_level"},
        "drought": {"drought_category"},
    }
    for kind, metrics in expected.items():
        assert kind in legacy.READING_VECTOR_REGISTRY
        configured = set(legacy.READING_VECTOR_REGISTRY[kind]["metrics"])
        assert metrics <= configured


def test_phase1_contract_metrics_match_canonical_registry():
    contract = load_food_resilience_contract()
    by_signal = {row["signal_id"]: row for row in contract["phase1_signals"]}
    expected = {
        "FOOD.P1.RAINFALL_30D": ("precipitation", "precipitation_pct_normal", "30d"),
        "FOOD.P1.RAINFALL_90D": ("precipitation", "precipitation_pct_normal", "90d"),
        "FOOD.P1.STREAMFLOW": ("reservoir", "streamflow", None),
        "FOOD.P1.GROUNDWATER": ("groundwater", "groundwater_level", None),
        "FOOD.P1.RESERVOIRS": ("reservoir", "reservoir_elevation", None),
        "FOOD.P1.DROUGHT_CLASS": ("drought", "drought_category", None),
    }
    for signal_id, (kind, metric, parameter_code) in expected.items():
        row = by_signal[signal_id]
        assert row["kind"] == kind
        assert row["metric"] == metric
        assert row.get("parameter_code") == parameter_code
        assert metric in legacy.READING_VECTOR_REGISTRY[kind]["metrics"]


def test_multisite_snapshot_withholds_arbitrary_station_value(tmp_path, monkeypatch):
    path = tmp_path / "readings.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"metric":"streamflow","site_no":"A","observed_date":"2026-10-25","value":10,"unit":"ft3/s","source_ref":"a"}',
                '{"metric":"streamflow","site_no":"B","observed_date":"2026-10-25","value":20,"unit":"ft3/s","source_ref":"b"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(legacy.READINGS_FILES, "food_test_multisite", path)

    signal = _latest_metric("food_test_multisite", "streamflow", 3)

    assert signal["available"] is True
    assert signal["spatial_scope"] == "MULTI_SITE_SNAPSHOT"
    assert signal["record_count"] == 2
    assert signal["site_count"] == 2
    assert signal["value"] is None
    assert signal["source_ref"] is None


def _write_grid_fixture(
    tmp_path,
    *,
    events,
    response_key_count=78,
    resolved_response_key_count=78,
    unresolved_response_keys=None,
):
    source_ref = (
        "https://api.miluma.lumapr.com/"
        "miluma-outage-api/outage/municipality/towns"
    )
    observed = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    normalized = []
    for event in events:
        normalized.append(
            {
                "event_id": event["event_id"],
                "event_type": "outage",
                "affected_area": event.get("affected_area", "San Juan / TEST"),
                "municipality": event.get("municipality", "San Juan"),
                "zone": event.get("zone", "TEST"),
                "start_time": observed,
                "source_ref": source_ref,
                "evidence_tier": "T2",
                "confidence": 80,
                "review_status": "needs_review",
            }
        )
    event_bytes = "".join(
        json.dumps(row, ensure_ascii=False) + "\n" for row in normalized
    ).encode("utf-8")
    event_path = tmp_path / "luma_live_incidents.jsonl"
    event_path.write_bytes(event_bytes)
    receipt = {
        "schema_version": "aguayluz.luma-live-receipt/v1",
        "status": "PASS",
        "source_ref": source_ref,
        "retrieval_utc": observed,
        "source_byte_sha256": "a" * 64,
        "source_byte_count": 123,
        "request_key_count": 78,
        "request_body_sha256": "b" * 64,
        "response_key_count": response_key_count,
        "resolved_response_key_count": resolved_response_key_count,
        "unresolved_response_keys": unresolved_response_keys or [],
        "event_count": len(normalized),
        "municipality_event_count": len(
            {row["municipality"] for row in normalized if row.get("municipality")}
        ),
        "granularity": "zone",
        "output_sha256": hashlib.sha256(event_bytes).hexdigest(),
        "output_byte_count": len(event_bytes),
    }
    (tmp_path / "luma_live_receipt.json").write_text(
        json.dumps(receipt),
        encoding="utf-8",
    )
    return receipt


def test_grid_outage_signal_raises_watch_from_verified_fresh_events(
    tmp_path, monkeypatch
):
    _write_grid_fixture(
        tmp_path,
        events=[
            {"event_id": "AYL_EVT_20261026_San_Juan_a"},
            {
                "event_id": "AYL_EVT_20261026_Caguas_b",
                "affected_area": "Caguas / TEST",
                "municipality": "Caguas",
            },
        ],
    )
    monkeypatch.setattr(legacy, "DATA", tmp_path)

    signal = _grid_outage_signal()

    assert signal["state"] == "WATCH"
    assert signal["availability_state"] == "AVAILABLE"
    assert signal["value"] == 2
    assert signal["municipality_count"] == 2
    assert signal["coverage_complete"] is True
    assert signal["observation_evidence_state"] == "FACT"
    assert signal["evidence_state"] == "COMPUTED"


def test_grid_outage_signal_allows_zero_only_with_complete_78_municipio_response(
    tmp_path, monkeypatch
):
    _write_grid_fixture(tmp_path, events=[])
    monkeypatch.setattr(legacy, "DATA", tmp_path)

    signal = _grid_outage_signal()

    assert signal["state"] == "NORMAL"
    assert signal["value"] == 0
    assert signal["coverage_complete"] is True
    assert signal["state_semantics"].startswith("MiLUMA town/zone warning only")


def test_grid_outage_signal_zero_partial_response_stays_unknown(tmp_path, monkeypatch):
    _write_grid_fixture(
        tmp_path,
        events=[],
        response_key_count=77,
        resolved_response_key_count=77,
    )
    monkeypatch.setattr(legacy, "DATA", tmp_path)

    signal = _grid_outage_signal()

    assert signal["state"] == "UNKNOWN"
    assert signal["availability_state"] == "PARTIAL_COVERAGE"
    assert signal["value"] == 0
    assert signal["coverage_complete"] is False


def test_grid_outage_signal_rejects_tampered_output(tmp_path, monkeypatch):
    _write_grid_fixture(
        tmp_path,
        events=[{"event_id": "AYL_EVT_20261026_San_Juan_a"}],
    )
    (tmp_path / "luma_live_incidents.jsonl").write_text(
        '{"tampered":true}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(legacy, "DATA", tmp_path)

    signal = _grid_outage_signal()

    assert signal["state"] == "UNKNOWN"
    assert signal["available"] is False
    assert signal["availability_state"] == "PROVENANCE_MISMATCH"


def test_grid_outage_signal_rejects_wrong_granularity(tmp_path, monkeypatch):
    _write_grid_fixture(
        tmp_path,
        events=[{"event_id": "AYL_EVT_20261026_San_Juan_a"}],
    )
    receipt_path = tmp_path / "luma_live_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["granularity"] = "municipio"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(legacy, "DATA", tmp_path)

    signal = _grid_outage_signal()

    assert signal["state"] == "UNKNOWN"
    assert signal["available"] is False
    assert signal["availability_state"] == "PROVENANCE_MISMATCH"
