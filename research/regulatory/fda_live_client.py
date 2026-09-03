"""Disabled FDA live-client contract with offline-only transport replay.

This module intentionally defines no concrete HTTP transport, no credential
loader, no persistence, no scheduler registration, no GUI/API capability, and
no entity-promotion behavior. Tests exercise it only with an injected fake
transport.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SECRET_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-session-id",
    }
)
_SECRET_QUERY_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "auth",
        "key",
        "session",
        "token",
    }
)
_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class FDAClientContractError(RuntimeError):
    """Base fail-closed error for disabled FDA live-client contract violations."""

    def __init__(self, message: str, *, receipt: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.receipt = dict(receipt or {})


class FDADisabledClientError(FDAClientContractError):
    """Raised when execution is attempted without offline replay authorization."""


class FDATransport(Protocol):
    """Dependency-injected transport contract.

    Implementations must be provided by tests or a separately authorized future
    operator workflow. This protocol must not grow a default socket transport.
    """

    def send(self, request: FDATransportRequest) -> FDATransportResponse:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class FDAClientControls:
    allowed_hosts: frozenset[str]
    source_profile_version: str
    terms_profile_version: str
    normalizer_version: str
    user_agent: str
    connect_timeout_seconds: float
    read_timeout_seconds: float
    max_body_bytes: int
    max_decompressed_bytes: int
    max_decompression_ratio: float
    max_attempts: int
    backoff_seconds: tuple[float, ...]
    request_budget: int
    accepted_media_types: tuple[str, ...] = ("application/json",)
    max_redirects: int = 3

    @classmethod
    def default_disabled(cls) -> FDAClientControls:
        return cls(
            allowed_hosts=frozenset(
                {
                    "api.fda.gov",
                    "open.fda.gov",
                    "www.fda.gov",
                    "www.accessdata.fda.gov",
                    "datadashboard.fda.gov",
                }
            ),
            source_profile_version="fda-live-source-registry/v1.4",
            terms_profile_version="fda-live-policy-receipts/v1.8",
            normalizer_version="fda-live-disabled-client/v1.8",
            user_agent="aguayluz-pr-disabled-fda-contract/1.8",
            connect_timeout_seconds=3.0,
            read_timeout_seconds=10.0,
            max_body_bytes=1_000_000,
            max_decompressed_bytes=2_000_000,
            max_decompression_ratio=20.0,
            max_attempts=3,
            backoff_seconds=(1.0, 2.0),
            request_budget=5,
        )


@dataclass(frozen=True, slots=True)
class FDATransportRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout: tuple[float, float] = (3.0, 10.0)


@dataclass(frozen=True, slots=True)
class FDATransportResponse:
    status_code: int
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    compressed_byte_count: int | None = None


@dataclass(frozen=True, slots=True)
class FDAFetchRequest:
    source_id: str
    method: str
    url: str
    expected_sha256: str | None = None
    accepted_media_types: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class FDACheckpoint:
    checkpoint_id: str
    source_profile_version: str
    normalizer_version: str
    request_fingerprint: str
    redacted_url: str
    last_accepted_sha256: str | None
    replay_state: str
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class FDAFetchResult:
    raw: bytes
    receipt: Mapping[str, object]
    checkpoint: FDACheckpoint


class FDADisabledLiveClient:
    """Disabled client shell that can only replay through an injected transport."""

    def __init__(
        self,
        *,
        transport: FDATransport | None = None,
        controls: FDAClientControls | None = None,
        offline_replay_authorized: bool = False,
    ) -> None:
        self._transport = transport
        self._controls = controls or FDAClientControls.default_disabled()
        self._offline_replay_authorized = offline_replay_authorized

    def fetch(
        self,
        request: FDAFetchRequest,
        *,
        checkpoint: FDACheckpoint | None = None,
    ) -> FDAFetchResult:
        if not self._offline_replay_authorized:
            raise FDADisabledClientError("FDA live client contract is disabled")
        if self._transport is None:
            raise FDADisabledClientError("FDA live client has no injected offline transport")

        self._validate_replay_checkpoint(request, checkpoint)
        current = self._validate_request_url(request.url)
        redacted_url, redactions = redact_url(current)
        accepted_media_types = request.accepted_media_types or self._controls.accepted_media_types
        attempts = 0
        redirects = 0
        retry_delays: list[float] = []
        last_receipt: dict[str, object] | None = None

        while True:
            attempts += 1
            if attempts > self._controls.request_budget:
                raise FDAClientContractError("request budget exhausted", receipt=last_receipt)

            transport_request = FDATransportRequest(
                method=request.method.upper(),
                url=current,
                headers={"User-Agent": self._controls.user_agent},
                timeout=(
                    self._controls.connect_timeout_seconds,
                    self._controls.read_timeout_seconds,
                ),
            )
            response = self._transport.send(transport_request)
            final_url = self._validate_request_url(response.url or current)
            redacted_final_url, final_redactions = redact_url(final_url)
            redactions = tuple(sorted(set(redactions) | set(final_redactions)))

            if response.status_code in {301, 302, 303, 307, 308}:
                redirects += 1
                if redirects > self._controls.max_redirects:
                    receipt = self._receipt(
                        request=request,
                        redacted_url=redacted_url,
                        redacted_final_url=redacted_final_url,
                        response=response,
                        sha256=None,
                        attempts=attempts,
                        retry_delays=retry_delays,
                        redactions=redactions,
                        retrieval_status="rejected",
                        error_class="redirect_limit_exceeded",
                    )
                    raise FDAClientContractError("redirect limit exceeded", receipt=receipt)
                location = response.headers.get("Location") or response.headers.get("location")
                if not location:
                    receipt = self._receipt(
                        request=request,
                        redacted_url=redacted_url,
                        redacted_final_url=redacted_final_url,
                        response=response,
                        sha256=None,
                        attempts=attempts,
                        retry_delays=retry_delays,
                        redactions=redactions,
                        retrieval_status="rejected",
                        error_class="redirect_missing_location",
                    )
                    raise FDAClientContractError("redirect missing location", receipt=receipt)
                try:
                    current = self._resolve_redirect(current, location)
                except FDAClientContractError as exc:
                    receipt = self._receipt(
                        request=request,
                        redacted_url=redacted_url,
                        redacted_final_url=redacted_final_url,
                        response=response,
                        sha256=None,
                        attempts=attempts,
                        retry_delays=retry_delays,
                        redactions=redactions,
                        retrieval_status="rejected",
                        error_class="redirect_host_escape",
                    )
                    raise FDAClientContractError(
                        "FDA redirect escaped allow-list", receipt=receipt
                    ) from exc
                redacted_url, redirect_redactions = redact_url(current)
                redactions = tuple(sorted(set(redactions) | set(redirect_redactions)))
                continue

            media_type = _media_type(response)
            digest = hashlib.sha256(response.body).hexdigest()
            retrieval_status = "success" if 200 <= response.status_code < 300 else "failed"
            receipt = self._receipt(
                request=request,
                redacted_url=redacted_url,
                redacted_final_url=redacted_final_url,
                response=response,
                sha256=digest,
                attempts=attempts,
                retry_delays=retry_delays,
                redactions=redactions,
                retrieval_status=retrieval_status,
                error_class=None,
            )
            last_receipt = receipt

            if response.status_code in _RETRYABLE_STATUSES and attempts < self._controls.max_attempts:
                retry_delays.append(self._retry_delay(response, attempts))
                continue
            if not 200 <= response.status_code < 300:
                error_class = (
                    "retry_exhausted"
                    if response.status_code in _RETRYABLE_STATUSES
                    else "non_retryable_http_status"
                )
                receipt["retrieval_status"] = "rate_limited" if response.status_code == 429 else "failed"
                receipt["error_class"] = error_class
                raise FDAClientContractError(
                    f"FDA transport rejected HTTP {response.status_code}", receipt=receipt
                )
            if media_type not in accepted_media_types:
                receipt["retrieval_status"] = "rejected"
                receipt["error_class"] = "media_type_rejected"
                raise FDAClientContractError("FDA media type rejected", receipt=receipt)
            self._validate_body_limits(response, receipt)
            if request.expected_sha256 and not hmac.compare_digest(digest, request.expected_sha256):
                receipt["retrieval_status"] = "rejected"
                receipt["error_class"] = "hash_mismatch"
                raise FDAClientContractError("FDA response hash mismatch", receipt=receipt)

            accepted_checkpoint = self._checkpoint(
                request=request,
                redacted_url=redacted_final_url,
                sha256=digest,
                response=response,
                replay_state="terminal",
            )
            receipt["checkpoint_id"] = accepted_checkpoint.checkpoint_id
            return FDAFetchResult(response.body, receipt, accepted_checkpoint)

    def _validate_request_url(self, url: str) -> str:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https":
            raise FDAClientContractError("FDA transport requires HTTPS")
        if not host or host not in self._controls.allowed_hosts:
            raise FDAClientContractError("FDA transport host is not allow-listed")
        if parts.username or parts.password:
            raise FDAClientContractError("FDA transport URL credentials are forbidden")
        return urlunsplit(parts)

    def _resolve_redirect(self, current_url: str, location: str) -> str:
        if location.startswith("/"):
            parts = urlsplit(current_url)
            target = urlunsplit((parts.scheme, parts.netloc, location, "", ""))
        else:
            target = location
        return self._validate_request_url(target)

    def _validate_body_limits(
        self, response: FDATransportResponse, receipt: dict[str, object]
    ) -> None:
        body_size = len(response.body)
        if body_size > self._controls.max_body_bytes:
            receipt["retrieval_status"] = "rejected"
            receipt["error_class"] = "body_too_large"
            raise FDAClientContractError("FDA response body exceeds byte limit", receipt=receipt)
        compressed_size = response.compressed_byte_count
        if body_size > self._controls.max_decompressed_bytes:
            receipt["retrieval_status"] = "rejected"
            receipt["error_class"] = "decompressed_body_too_large"
            raise FDAClientContractError(
                "FDA response exceeds decompressed byte limit", receipt=receipt
            )
        if compressed_size and body_size / compressed_size > self._controls.max_decompression_ratio:
            receipt["retrieval_status"] = "rejected"
            receipt["error_class"] = "decompression_ratio_exceeded"
            raise FDAClientContractError(
                "FDA response exceeds decompression ratio limit", receipt=receipt
            )

    def _validate_replay_checkpoint(
        self, request: FDAFetchRequest, checkpoint: FDACheckpoint | None
    ) -> None:
        if checkpoint is None:
            return
        expected = self._request_fingerprint(request)
        if checkpoint.source_profile_version != self._controls.source_profile_version:
            raise FDAClientContractError("FDA checkpoint source profile drift")
        if checkpoint.normalizer_version != self._controls.normalizer_version:
            raise FDAClientContractError("FDA checkpoint normalizer drift")
        if checkpoint.request_fingerprint != expected:
            raise FDAClientContractError("FDA checkpoint request drift")
        if checkpoint.replay_state not in {"terminal", "partial"}:
            raise FDAClientContractError("FDA checkpoint replay state rejected")

    def _receipt(
        self,
        *,
        request: FDAFetchRequest,
        redacted_url: str,
        redacted_final_url: str,
        response: FDATransportResponse,
        sha256: str | None,
        attempts: int,
        retry_delays: Sequence[float],
        redactions: Sequence[str],
        retrieval_status: str,
        error_class: str | None,
    ) -> dict[str, object]:
        digest_material = "|".join(
            [
                request.source_id,
                redacted_final_url,
                str(response.status_code),
                sha256 or "no-body",
                self._controls.normalizer_version,
            ]
        ).encode("utf-8")
        return {
            "receipt_id": f"AYL_REGRCPT_FDA_{hashlib.sha256(digest_material).hexdigest()[:24]}",
            "provider": "FDA",
            "source_id": request.source_id,
            "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "request_locator": redacted_url,
            "final_url": redacted_final_url,
            "method": request.method.upper(),
            "http_status": response.status_code,
            "sha256": sha256,
            "byte_count": len(response.body),
            "media_type": _media_type(response),
            "retrieval_status": retrieval_status,
            "retry_count": attempts - 1,
            "retry_delays_seconds": tuple(retry_delays),
            "terms_profile_version": self._controls.terms_profile_version,
            "source_profile_version": self._controls.source_profile_version,
            "normalizer_version": self._controls.normalizer_version,
            "etag": response.headers.get("ETag") or response.headers.get("etag"),
            "last_modified": response.headers.get("Last-Modified")
            or response.headers.get("last-modified"),
            "redactions": tuple(sorted(set(redactions))),
            "error_class": error_class,
        }

    def _checkpoint(
        self,
        *,
        request: FDAFetchRequest,
        redacted_url: str,
        sha256: str,
        response: FDATransportResponse,
        replay_state: str,
    ) -> FDACheckpoint:
        fingerprint = self._request_fingerprint(request)
        material = "|".join(
            [
                self._controls.source_profile_version,
                self._controls.normalizer_version,
                fingerprint,
                sha256,
            ]
        ).encode("utf-8")
        return FDACheckpoint(
            checkpoint_id=f"AYL_FDA_CKPT_{hashlib.sha256(material).hexdigest()[:24]}",
            source_profile_version=self._controls.source_profile_version,
            normalizer_version=self._controls.normalizer_version,
            request_fingerprint=fingerprint,
            redacted_url=redacted_url,
            last_accepted_sha256=sha256,
            replay_state=replay_state,
            etag=response.headers.get("ETag") or response.headers.get("etag"),
            last_modified=response.headers.get("Last-Modified")
            or response.headers.get("last-modified"),
        )

    def _request_fingerprint(self, request: FDAFetchRequest) -> str:
        redacted_url, _ = redact_url(self._validate_request_url(request.url))
        material = {
            "accepted_media_types": request.accepted_media_types
            or self._controls.accepted_media_types,
            "method": request.method.upper(),
            "normalizer_version": self._controls.normalizer_version,
            "source_id": request.source_id,
            "source_profile_version": self._controls.source_profile_version,
            "url": redacted_url,
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()

    def _retry_delay(self, response: FDATransportResponse, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After") or response.headers.get("retry-after")
        if retry_after and retry_after.isdigit():
            return float(retry_after)
        index = min(attempt - 1, len(self._controls.backoff_seconds) - 1)
        return self._controls.backoff_seconds[index]


class OfflineFakeFDATransport:
    """Deterministic fixture transport for contract tests."""

    def __init__(self, responses: Sequence[FDATransportResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[FDATransportRequest] = []

    def send(self, request: FDATransportRequest) -> FDATransportResponse:
        self.requests.append(request)
        if not self._responses:
            raise FDAClientContractError("offline FDA transport fixture exhausted")
        return self._responses.pop(0)


def redact_headers(headers: Mapping[str, str]) -> tuple[dict[str, str], tuple[str, ...]]:
    redacted: dict[str, str] = {}
    redactions: list[str] = []
    for key, value in headers.items():
        if key.lower() in _SECRET_HEADER_NAMES:
            redacted[key] = "[REDACTED]"
            redactions.append(f"header:{key.lower()}")
        else:
            redacted[key] = value
    return redacted, tuple(redactions)


def redact_url(url: str) -> tuple[str, tuple[str, ...]]:
    parts = urlsplit(url)
    redactions: list[str] = []
    query_items: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _SECRET_QUERY_NAMES:
            query_items.append((key, "[REDACTED]"))
            redactions.append(f"query:{key.lower()}")
        else:
            query_items.append((key, value))
    redacted_query = urlencode(query_items)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, redacted_query, parts.fragment)), tuple(redactions)


def _media_type(response: FDATransportResponse) -> str:
    content_type = response.headers.get("Content-Type") or response.headers.get("content-type") or ""
    return content_type.split(";", 1)[0].strip().lower() or "application/octet-stream"
