"""Contract tests for the read-only regulatory observation API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.regulatory_api as regulatory_api  # noqa: E402
from server.backend.app import app  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/regulatory/framework_cases_v0_2.json"


def _cases() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _observations() -> list[dict]:
    return _cases()["observations"]


def _receipts() -> list[dict]:
    # Same derivation as tests/test_regulatory_db.py: receipt ids come from what the
    # fixture observations actually reference, not reconstructed from provider names.
    import hashlib

    cases = _cases()
    receipt_providers: dict[str, str] = {}
    for o in cases["observations"]:
        receipt_providers.setdefault(o["source_receipt_id"], o["provider"])
    receipts = []
    for receipt_id, provider in receipt_providers.items():
        content = cases["raw_payloads"][provider].encode("utf-8")
        receipts.append({
            "receipt_id": receipt_id,
            "provider": provider,
            "retrieved_at": "2026-08-04T19:00:00Z",
            "request_locator": f"fixture://{provider.lower()}/record/001",
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_count": len(content),
            "media_type": "application/json",
            "retrieval_status": "success",
            "http_status": 200,
            "redactions": [],
        })
    return receipts


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(regulatory_api, "load_regulatory_observations", _observations)
    monkeypatch.setattr(regulatory_api, "load_regulatory_receipts", _receipts)
    with TestClient(app) as test_client:
        yield test_client


def test_summary_counts_and_scope_statement(client):
    body = client.get("/regulatory/summary").json()

    assert "never a claim" in body["scope"]["statement"]
    assert body["counts"] == {"observations": len(_observations()), "receipts": len(_receipts())}
    assert body["provider"]["USGS"] == 1
    assert body["provider"]["FDA"] == 2  # AYL_REGOBS_FDA_001 + AYL_REGOBS_FDA_DUPLICATE
    assert set(body["freshness_state"]) >= {"current", "historical", "stale", "conflicting"}


def test_observations_list_is_unfiltered_by_default(client):
    body = client.get("/regulatory/observations").json()
    assert body["total"] == len(_observations())
    assert len(body["items"]) == len(_observations())


def test_observations_filter_by_provider(client):
    body = client.get("/regulatory/observations", params={"provider": "USGS"}).json()
    assert body["total"] == 1
    assert body["items"][0]["provider"] == "USGS"


def test_observations_filter_by_freshness_state(client):
    body = client.get("/regulatory/observations", params={"freshness_state": "stale"}).json()
    assert body["total"] == 1
    assert body["items"][0]["freshness_state"] == "stale"


def test_observations_filter_by_record_family(client):
    body = client.get("/regulatory/observations", params={"record_family": "enforcement"}).json()
    assert all(item["record_family"] == "enforcement" for item in body["items"])
    assert body["total"] >= 1


def test_observations_pagination(client):
    first_page = client.get("/regulatory/observations", params={"limit": 2, "offset": 0}).json()
    second_page = client.get("/regulatory/observations", params={"limit": 2, "offset": 2}).json()
    assert len(first_page["items"]) == 2
    assert first_page["total"] == second_page["total"]
    assert {i["observation_id"] for i in first_page["items"]}.isdisjoint(
        {i["observation_id"] for i in second_page["items"]}
    )


def test_observation_detail_includes_receipt(client):
    obs_id = "AYL_REGOBS_USGS_001"
    body = client.get(f"/regulatory/observations/{obs_id}").json()
    assert body["observation_id"] == obs_id
    assert body["receipt"]["receipt_id"] == body["source_receipt_id"]


def test_observation_detail_404_for_unknown_id(client):
    resp = client.get("/regulatory/observations/AYL_REGOBS_USGS_DOES_NOT_EXIST")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "regulatory_observation_not_found"


def test_receipt_detail_by_id(client):
    receipt_id = _receipts()[0]["receipt_id"]
    body = client.get(f"/regulatory/receipts/{receipt_id}").json()
    assert body["receipt_id"] == receipt_id


def test_receipt_detail_404_for_unknown_id(client):
    resp = client.get("/regulatory/receipts/AYL_REGRCPT_DOES_NOT_EXIST")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "regulatory_receipt_not_found"


def test_receipt_detail_never_leaks_secret_shaped_fields(client):
    receipt_id = _receipts()[0]["receipt_id"]
    body = client.get(f"/regulatory/receipts/{receipt_id}").json()
    serialized = json.dumps(body).lower()
    assert "authorization" not in serialized
    assert "bearer " not in serialized
