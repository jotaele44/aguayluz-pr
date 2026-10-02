from fastapi.testclient import TestClient
from server.backend.app import app


def test_shadow_consumer_routes_are_mounted_and_discoverable():
    client = TestClient(app)
    health = client.get('/monitoring/health')
    assert health.status_code == 200
    assert health.json()['shadow_water_pipeline'] is True
    assert client.get('/water-disruption/validation-queue').status_code == 200
    console = client.get('/water-disruption/console')
    assert console.status_code == 200
    assert 'Shadow mode' in console.text


def test_non_shadow_intake_fails_closed():
    client = TestClient(app)
    response = client.post('/water-disruption/intake', json={'candidate_id': 'x'}, headers={'Idempotency-Key': 'k', 'X-Shadow-Mode': 'false'})
    assert response.status_code == 409
    assert response.json()['detail'] == 'shadow_mode_required'


def test_incident_listing_disables_notifications():
    client = TestClient(app)
    payload = client.get('/water-disruption/incidents').json()
    assert payload['shadow_mode'] is True
    assert payload['notifications_enabled'] is False


def test_water_disruption_rejects_reserved_nonlocal_client():
    local_client = TestClient(app, client=("192.168.1.20", 50000))
    remote_client = TestClient(app, client=("203.0.113.10", 50000))

    local = local_client.get('/water-disruption/validation-queue')
    remote = remote_client.post(
        '/water-disruption/intake',
        json={'candidate_id': 'remote'},
        headers={'Idempotency-Key': 'remote-key', 'X-Shadow-Mode': 'true'},
    )

    assert local.status_code == 200
    assert remote.status_code == 403
