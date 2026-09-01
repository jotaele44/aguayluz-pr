from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.backend.water_disruption_api import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_laguna_control_plane_is_exposed_on_existing_shadow_surface():
    response = client().get("/water-disruption/incidents")
    assert response.status_code == 200
    payload = response.json()
    control = payload["laguna_cartagena"]
    assert control["schema_version"] == "aguayluz.laguna-cartagena-control-plane/v0.2"
    assert control["current_condition"]["status"] == "unknown"
    assert control["alerts_enabled"] is False
    assert control["automatic_control_actions_enabled"] is False


def test_existing_console_renders_unknown_safe_laguna_view():
    response = client().get("/water-disruption/console")
    assert response.status_code == 200
    assert "Laguna Cartagena current-condition control plane" in response.text
    assert "Unknown-safe" in response.text
    assert "Notifications and production exports are disabled" in response.text
