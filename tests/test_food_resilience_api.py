from fastapi.testclient import TestClient

from server.backend.food_app import app


client = TestClient(app)


def test_food_state_is_phase1_and_higher_phase_metrics_are_locked():
    response = client.get('/food-resilience/state')
    assert response.status_code == 200
    state = response.json()
    assert state['vector_id'] == 'FOOD_SYSTEM_RESILIENCE'
    assert state['activation_phase'] == 1
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
