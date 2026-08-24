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
