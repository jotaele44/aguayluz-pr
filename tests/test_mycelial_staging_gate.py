from __future__ import annotations

import importlib
from datetime import date
from types import ModuleType

from fastapi.testclient import TestClient

from research.mycelial.staging import (
    CAPABILITY_CLASSIFICATION,
    FEATURE_FLAG_ENV,
    STAGING_EXPIRES_ON,
    TRACKING_REFERENCE,
    feature_flag_enabled,
)


def _app_module() -> ModuleType:
    return importlib.import_module("research.mycelial.app")


def test_exported_asgi_app_is_disabled_without_feature_flag(monkeypatch):
    monkeypatch.delenv(FEATURE_FLAG_ENV, raising=False)
    app_module = importlib.reload(_app_module())
    response = TestClient(app_module.app).get("/research/mycelial/status")
    assert response.status_code == 404
    assert app_module.app.state.research_routes_enabled is False
    assert app_module.app.state.capability_classification == CAPABILITY_CLASSIFICATION
    assert app_module.app.state.tracking_reference == TRACKING_REFERENCE
    assert app_module.app.state.staging_expires_on == STAGING_EXPIRES_ON.isoformat()
    assert app_module.app.state.feature_flag == FEATURE_FLAG_ENV


def test_feature_flag_requires_exact_opt_in_value():
    assert feature_flag_enabled({}) is False
    assert feature_flag_enabled({FEATURE_FLAG_ENV: "true"}) is False
    assert feature_flag_enabled({FEATURE_FLAG_ENV: "0"}) is False
    assert feature_flag_enabled({FEATURE_FLAG_ENV: "1"}) is True


def test_factory_gate_and_staging_expiry_fail_closed():
    create_app = _app_module().create_app
    disabled = create_app(
        enable_research_routes=False,
        today=date(2026, 8, 3),
    )
    assert TestClient(disabled).get("/research/mycelial/status").status_code == 404

    expired = create_app(
        enable_research_routes=True,
        today=date(2027, 1, 1),
    )
    assert TestClient(expired).get("/research/mycelial/status").status_code == 404
    assert expired.state.research_routes_enabled is False


def test_explicit_unexpired_factory_exposes_only_staged_research_routes():
    create_app = _app_module().create_app
    application = create_app(
        enable_research_routes=True,
        today=date(2026, 8, 3),
    )
    client = TestClient(application)
    status = client.get("/research/mycelial/status")
    assert status.status_code == 200
    assert status.json()["capability_classification"] == CAPABILITY_CLASSIFICATION
    assert status.json()["tracking_reference"] == TRACKING_REFERENCE
    assert status.json()["staging_expires_on"] == STAGING_EXPIRES_ON.isoformat()
    assert status.json()["feature_flag"] == FEATURE_FLAG_ENV
    assert application.state.research_routes_enabled is True
