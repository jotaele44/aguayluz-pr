from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from research.regulatory.fda_live_client_contract import (
    DisabledFDALiveClient,
    FDAClientContractError,
    FDAClientErrorCode,
    FDALiveClientConfig,
    FDAResponse,
    OfflineFakeFDATransport,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/regulatory/fda_live_client_transport_v1_8.json"
RECEIPTS = ROOT / "research/regulatory/fda_live_contract_receipts_v1_8.json"
MODULE = ROOT / "research/regulatory/fda_live_client_contract.py"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fake_transport() -> OfflineFakeFDATransport:
    return OfflineFakeFDATransport.from_fixture(load_fixture())


def test_receipts_are_frozen_without_provider_acquisition_or_activation() -> None:
    receipts = json.loads(RECEIPTS.read_text(encoding="utf-8"))
    assert receipts["status"] == "frozen_documentation_receipts_only"
    assert receipts["provider_acquisition_executed"] is False
    assert receipts["network_client_implemented"] is False
    assert receipts["real_credentials_accepted"] is False
    assert receipts["production_persistence_allowed"] is False
    assert receipts["scheduler_registration_allowed"] is False
    assert receipts["requires_separate_explicit_authorization"] is True

    contract = receipts["source_profile_contract"]
    assert sorted(contract["allowed_hosts"]) == sorted(
        [
            "api.fda.gov",
            "datadashboard.fda.gov",
            "open.fda.gov",
            "www.accessdata.fda.gov",
            "www.fda.gov",
        ]
    )
    assert contract["redirects_to_unlisted_hosts_allowed"] is False
    assert contract["credentials_allowed"] is False
    assert contract["raw_bytes_required"] is True
    assert contract["sha256_required"] is True
    assert contract["secret_redaction_required"] is True


def test_client_defaults_to_disabled_and_has_no_default_transport() -> None:
    disabled = DisabledFDALiveClient()
    with pytest.raises(FDAClientContractError) as disabled_error:
        disabled.get("FDA_DEVICE_REGISTRATION_LISTING_OPENFDA", "https://api.fda.gov/test")
    assert disabled_error.value.code == FDAClientErrorCode.CLIENT_DISABLED

    enabled_without_transport = DisabledFDALiveClient(enabled=True)
    with pytest.raises(FDAClientContractError) as transport_error:
        enabled_without_transport.get(
            "FDA_DEVICE_REGISTRATION_LISTING_OPENFDA",
            "https://api.fda.gov/device/registrationlisting.json?limit=1",
        )
    assert transport_error.value.code == FDAClientErrorCode.TRANSPORT_REQUIRED


def test_success_receipt_hash_and_checkpoint_are_deterministic() -> None:
    transport = fake_transport()
    client = DisabledFDALiveClient(transport, enabled=True)
    result = client.get(
        "FDA_DEVICE_REGISTRATION_LISTING_OPENFDA",
        "https://api.fda.gov/device/registrationlisting.json?limit=1",
        normalizer_version="fda-contract-test/v1",
    )

    assert transport.request_count == 1
    assert result.receipt.sha256 == hashlib.sha256(result.raw_bytes).hexdigest()
    assert result.receipt.byte_count == len(result.raw_bytes)
    assert result.receipt.receipt_id.endswith(result.receipt.sha256[:24])
    assert result.checkpoint.last_accepted_raw_sha256 == result.receipt.sha256
    assert result.checkpoint.last_accepted_raw_receipt_id == result.receipt.receipt_id
    assert result.checkpoint.replay_state == "terminal"


def test_redirect_escape_is_fail_closed() -> None:
    client = DisabledFDALiveClient(fake_transport(), enabled=True)
    with pytest.raises(FDAClientContractError) as error:
        client.get(
            "FDA_DEVICE_REGISTRATION_LISTING_OPENFDA",
            "https://api.fda.gov/device/registrationlisting.json?redirect=escape",
        )
    assert error.value.code == FDAClientErrorCode.REDIRECT_ESCAPE


def test_429_honors_retry_after_without_sleeping_or_live_transport() -> None:
    transport = fake_transport()
    client = DisabledFDALiveClient(transport, enabled=True)
    result = client.get(
        "FDA_DEVICE_ENFORCEMENT_OPENFDA",
        "https://api.fda.gov/device/enforcement.json?rate_limit=1",
    )
    assert transport.request_count == 2
    assert result.receipt.retry_count == 1
    assert result.receipt.retry_plan == ("retry-after:2",)


def test_5xx_uses_bounded_backoff_and_then_succeeds() -> None:
    transport = fake_transport()
    client = DisabledFDALiveClient(transport, enabled=True)
    result = client.get(
        "FDA_DEVICE_ENFORCEMENT_OPENFDA",
        "https://api.fda.gov/device/enforcement.json?transient=1",
    )
    assert transport.request_count == 3
    assert result.receipt.retry_count == 2
    assert result.receipt.retry_plan == ("backoff:0.5", "backoff:1.0")


def test_non_retryable_4xx_is_not_retried() -> None:
    transport = fake_transport()
    client = DisabledFDALiveClient(transport, enabled=True)
    with pytest.raises(FDAClientContractError) as error:
        client.get(
            "FDA_DEVICE_ENFORCEMENT_OPENFDA",
            "https://api.fda.gov/device/enforcement.json?missing=1",
        )
    assert error.value.code == FDAClientErrorCode.NON_RETRYABLE_HTTP_STATUS
    assert transport.request_count == 1


def test_hash_mismatch_is_fail_closed_and_not_retried() -> None:
    transport = fake_transport()
    client = DisabledFDALiveClient(transport, enabled=True)
    with pytest.raises(FDAClientContractError) as error:
        client.get(
            "FDA_DEVICE_REGISTRATION_LISTING_OPENFDA",
            "https://api.fda.gov/device/registrationlisting.json?limit=1",
            expected_sha256="0" * 64,
        )
    assert error.value.code == FDAClientErrorCode.HASH_MISMATCH
    assert transport.request_count == 1


def test_oversize_body_is_rejected_before_receipt_acceptance() -> None:
    body = b"x" * 64
    transport = OfflineFakeFDATransport(
        {
            "GET https://api.fda.gov/device/enforcement.json?oversize=1": [
                FDAResponse(200, (("content-type", "application/json"),), body)
            ]
        }
    )
    client = DisabledFDALiveClient(
        transport,
        enabled=True,
        config=FDALiveClientConfig(max_body_bytes=16),
    )
    with pytest.raises(FDAClientContractError) as error:
        client.get(
            "FDA_DEVICE_ENFORCEMENT_OPENFDA",
            "https://api.fda.gov/device/enforcement.json?oversize=1",
        )
    assert error.value.code == FDAClientErrorCode.OVERSIZE_BODY


def test_decompression_limit_is_fail_closed() -> None:
    compressed = gzip.compress(b"a" * 1024)
    transport = OfflineFakeFDATransport(
        {
            "GET https://api.fda.gov/device/enforcement.json?gzip=1": [
                FDAResponse(
                    200,
                    (("content-type", "application/json"), ("content-encoding", "gzip")),
                    compressed,
                )
            ]
        }
    )
    client = DisabledFDALiveClient(
        transport,
        enabled=True,
        config=FDALiveClientConfig(max_decompressed_bytes=128, max_decompression_ratio=2),
    )
    with pytest.raises(FDAClientContractError) as error:
        client.get(
            "FDA_DEVICE_ENFORCEMENT_OPENFDA",
            "https://api.fda.gov/device/enforcement.json?gzip=1",
        )
    assert error.value.code == FDAClientErrorCode.DECOMPRESSION_LIMIT


def test_secret_sentinel_is_redacted_and_checkpoint_replay_is_bound_to_hash() -> None:
    url = "https://api.fda.gov/device/enforcement.json?api_key=SENTINEL_OPENFDA_KEY&limit=1"
    first_transport = fake_transport()
    first_client = DisabledFDALiveClient(
        first_transport,
        enabled=True,
        secret_sentinels=("SENTINEL_OPENFDA_KEY",),
    )
    first = first_client.get("FDA_DEVICE_ENFORCEMENT_OPENFDA", url)

    serialized = json.dumps(
        {"receipt": first.receipt.as_dict(), "checkpoint": first.checkpoint.as_dict()},
        sort_keys=True,
    )
    assert "SENTINEL_OPENFDA_KEY" not in serialized
    assert "query:api_key" in first.receipt.redactions

    replay_client = DisabledFDALiveClient(
        fake_transport(),
        enabled=True,
        secret_sentinels=("SENTINEL_OPENFDA_KEY",),
    )
    replay = replay_client.replay_from_checkpoint(
        "FDA_DEVICE_ENFORCEMENT_OPENFDA",
        url,
        first.checkpoint,
    )
    assert replay.receipt.sha256 == first.receipt.sha256


def test_real_credentials_are_rejected_without_leaking_values() -> None:
    client = DisabledFDALiveClient(fake_transport(), enabled=True)
    with pytest.raises(FDAClientContractError) as error:
        client.get(
            "FDA_DEVICE_ENFORCEMENT_OPENFDA",
            "https://api.fda.gov/device/enforcement.json?api_key=real-secret-value",
        )
    assert error.value.code == FDAClientErrorCode.CREDENTIALS_FORBIDDEN
    assert "real-secret-value" not in str(error.value)


def test_module_contains_no_socket_persistence_scheduler_or_default_http_client() -> None:
    source = MODULE.read_text(encoding="utf-8").lower()
    forbidden = (
        "import httpx",
        "import requests",
        "urllib.request",
        "import socket",
        "sqlite3",
        "sqlalchemy",
        "apscheduler",
        "subprocess",
        "default_http",
    )
    assert not any(token in source for token in forbidden)
