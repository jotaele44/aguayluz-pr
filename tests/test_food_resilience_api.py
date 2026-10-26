from fastapi.testclient import TestClient
from server.backend import main as legacy
from server.backend.app import app
from server.backend.food_resilience_api import (
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
