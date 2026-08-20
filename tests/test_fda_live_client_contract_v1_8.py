from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from research.regulatory.fda_live_client import (
    FDAClientContractError,
    FDADisabledClientError,
    FDADisabledLiveClient,
    FDAFetchRequest,
    FDATransportResponse,
    OfflineFakeFDATransport,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_RECEIPTS = ROOT / "research/regulatory/fda_live_policy_receipts_v1_8.json"
FIXTURE = ROOT / "tests/fixtures/regulatory/fda_live_transport_replay_v1_8.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_request() -> tuple[FDAFetchRequest, bytes]:
    fixture = load_json(FIXTURE)
    body = fixture["body"].encode("utf-8")
    assert hashlib.sha256(body).hexdigest() == fixture["sha256"]
    return (
        FDAFetchRequest(
            source_id=fixture["source_id"],
            method="GET",
            url=fixture["request_url"],
            expected_sha256=fixture["sha256"],
        ),
        body,
    )


def client_for(*responses: FDATransportResponse) -> tuple[FDADisabledLiveClient, OfflineFakeFDATransport]:
    transport = OfflineFakeFDATransport(responses)
    return (
        FDADisabledLiveClient(transport=transport, offline_replay_authorized=True),
        transport,
    )


def ok_response(body: bytes, **headers: str) -> FDATransportResponse:
    return FDATransportResponse(
        status_code=200,
        url="https://api.fda.gov/device/enforcement.json?limit=1",
        headers={"Content-Type": "application/json", **headers},
        body=body,
    )


def test_policy_receipts_are_frozen_without_activation_or_provider_acquisition() -> None:
    receipts = load_json(POLICY_RECEIPTS)
    assert receipts["status"] == "frozen_policy_receipts_only_no_provider_acquisition"
    assert receipts["provider_acquisition_calls_executed"] is False
    assert receipts["network_implementation_allowed"] is False
    assert receipts["scheduler_registration_allowed"] is False
    assert receipts["production_persistence_allowed"] is False
    assert receipts["credentials_allowed"] is False
    assert receipts["gui_api_capabilities_allowed"] is False
    assert receipts["automatic_entity_promotion_allowed"] is False
    assert receipts["compliance_inference_allowed"] is False
    assert receipts["requires_separate_explicit_authorization"] is True
    assert {item["source_host"] for item in receipts["receipts"]} == {
        "open.fda.gov",
        "www.fda.gov",
        "local_repository",
    }
    assert all(len(item["sha256"]) == 64 for item in receipts["receipts"])
    rate_receipt = next(
        item for item in receipts["receipts"] if item["source_kind"] == "authentication_and_rate_limit_documentation"
    )
    snapshot = rate_receipt["rate_limit_assertions"]["official_snapshot_values"]
    assert snapshot["without_api_key"] == {
        "requests_per_minute_per_ip": 240,
        "requests_per_day_per_ip": 1000,
    }
    assert snapshot["with_api_key"] == {
        "requests_per_minute_per_key": 240,
        "requests_per_day_per_key": 120000,
    }


def test_client_defaults_to_disabled_and_has_no_default_transport() -> None:
    request, _ = fixture_request()
    with pytest.raises(FDADisabledClientError, match="disabled"):
        FDADisabledLiveClient().fetch(request)
    with pytest.raises(FDADisabledClientError, match="no injected offline transport"):
        FDADisabledLiveClient(offline_replay_authorized=True).fetch(request)


def test_success_receipt_and_checkpoint_replay_are_stable() -> None:
    request, body = fixture_request()
    client, transport = client_for(ok_response(body, ETag='"abc"', **{"Last-Modified": "Wed, 05 Aug 2026 04:00:00 GMT"}))
    result = client.fetch(request)
    replay_client, replay_transport = client_for(ok_response(body, ETag='"abc"'))
    replay = replay_client.fetch(request, checkpoint=result.checkpoint)

    assert result.raw == body
    assert result.receipt["sha256"] == hashlib.sha256(body).hexdigest()
    assert result.receipt["retry_count"] == 0
    assert result.receipt["checkpoint_id"] == result.checkpoint.checkpoint_id
    assert result.checkpoint.checkpoint_id == replay.checkpoint.checkpoint_id
    assert len(transport.requests) == 1
    assert len(replay_transport.requests) == 1


def test_redirect_escape_is_rejected_before_second_request() -> None:
    request, _ = fixture_request()
    client, transport = client_for(
        FDATransportResponse(
            status_code=302,
            url=request.url,
            headers={"Location": "https://example.com/escape"},
        )
    )
    with pytest.raises(FDAClientContractError, match="redirect escaped") as error:
        client.fetch(request)
    assert len(transport.requests) == 1
    assert error.value.receipt["error_class"] == "redirect_host_escape"


def test_429_retry_after_is_honored_without_sleeping() -> None:
    request, body = fixture_request()
    client, transport = client_for(
        FDATransportResponse(
            status_code=429,
            url=request.url,
            headers={"Content-Type": "application/json", "Retry-After": "7"},
            body=b'{"error":"rate"}',
        ),
        ok_response(body),
    )
    result = client.fetch(request)
    assert len(transport.requests) == 2
    assert result.receipt["retry_count"] == 1
    assert result.receipt["retry_delays_seconds"] == (7.0,)


def test_5xx_uses_bounded_backoff_and_then_succeeds() -> None:
    request, body = fixture_request()
    client, transport = client_for(
        FDATransportResponse(status_code=503, url=request.url, body=b"unavailable"),
        FDATransportResponse(status_code=502, url=request.url, body=b"bad gateway"),
        ok_response(body),
    )
    result = client.fetch(request)
    assert len(transport.requests) == 3
    assert result.receipt["retry_delays_seconds"] == (1.0, 2.0)


def test_non_retryable_4xx_fails_closed_without_retry() -> None:
    request, _ = fixture_request()
    client, transport = client_for(
        FDATransportResponse(status_code=404, url=request.url, body=b"missing")
    )
    with pytest.raises(FDAClientContractError) as error:
        client.fetch(request)
    assert len(transport.requests) == 1
    assert error.value.receipt["error_class"] == "non_retryable_http_status"


def test_hash_mismatch_fails_closed_without_retry() -> None:
    request, body = fixture_request()
    bad_request = replace(request, expected_sha256="0" * 64)
    client, transport = client_for(ok_response(body))
    with pytest.raises(FDAClientContractError, match="hash mismatch") as error:
        client.fetch(bad_request)
    assert len(transport.requests) == 1
    assert error.value.receipt["error_class"] == "hash_mismatch"


def test_oversized_body_and_decompression_limit_are_rejected() -> None:
    request, _ = fixture_request()
    large = b"x" * 1_000_001
    client, _ = client_for(ok_response(large))
    with pytest.raises(FDAClientContractError, match="byte limit") as body_error:
        client.fetch(replace(request, expected_sha256=hashlib.sha256(large).hexdigest()))
    assert body_error.value.receipt["error_class"] == "body_too_large"

    expanded = b"x" * 101
    ratio_client, _ = client_for(
        FDATransportResponse(
            status_code=200,
            url=request.url,
            headers={"Content-Type": "application/json"},
            body=expanded,
            compressed_byte_count=5,
        )
    )
    with pytest.raises(FDAClientContractError, match="decompression ratio") as ratio_error:
        ratio_client.fetch(replace(request, expected_sha256=hashlib.sha256(expanded).hexdigest()))
    assert ratio_error.value.receipt["error_class"] == "decompression_ratio_exceeded"


def test_secret_sentinels_are_redacted_from_receipts_and_checkpoints() -> None:
    request, body = fixture_request()
    secret_value = "sk_live_DO_NOT_LEAK_123"
    secret_request = replace(request, url=f"{request.url}&token={secret_value}")
    client, _ = client_for(
        FDATransportResponse(
            status_code=200,
            url=f"{request.url}&token={secret_value}",
            headers={"Content-Type": "application/json"},
            body=body,
        )
    )
    result = client.fetch(secret_request)
    serialized = json.dumps(
        {"receipt": result.receipt, "checkpoint": asdict(result.checkpoint)},
        sort_keys=True,
    )
    assert secret_value not in serialized
    assert "REDACTED" in serialized
    assert "query:token" in serialized


def test_checkpoint_replay_rejects_request_drift() -> None:
    request, body = fixture_request()
    client, _ = client_for(ok_response(body))
    result = client.fetch(request)
    changed = replace(request, url="https://api.fda.gov/device/enforcement.json?limit=2")
    replay_client, _ = client_for(ok_response(body))
    with pytest.raises(FDAClientContractError, match="request drift"):
        replay_client.fetch(changed, checkpoint=result.checkpoint)


def test_module_contains_no_socket_http_persistence_scheduler_or_capability_registration() -> None:
    source = (ROOT / "research/regulatory/fda_live_client.py").read_text(encoding="utf-8").lower()
    forbidden = (
        "import httpx",
        "import requests",
        "urllib.request",
        "import socket",
        "sqlite3",
        "sqlalchemy",
        "apscheduler",
        "fastapi",
        "flask",
        "schedule.",
        "entity_promotion",
    )
    assert not any(token in source for token in forbidden)
