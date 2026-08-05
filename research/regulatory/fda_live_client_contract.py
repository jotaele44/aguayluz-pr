"""Disabled FDA live-client contract with offline transport fixtures only.

This module defines request/response validation, retry, receipt, redaction, and
checkpoint behavior for a future FDA acquisition client. It intentionally has no
HTTP implementation, default transport, scheduler registration, persistence,
GUI/API capability, entity promotion, or compliance inference.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class FDAClientErrorCode(StrEnum):
    CLIENT_DISABLED = "CLIENT_DISABLED"
    TRANSPORT_REQUIRED = "TRANSPORT_REQUIRED"
    HTTPS_REQUIRED = "HTTPS_REQUIRED"
    HOST_NOT_ALLOWED = "HOST_NOT_ALLOWED"
    REDIRECT_ESCAPE = "REDIRECT_ESCAPE"
    REDIRECT_LIMIT_EXCEEDED = "REDIRECT_LIMIT_EXCEEDED"
    REQUEST_BUDGET_EXHAUSTED = "REQUEST_BUDGET_EXHAUSTED"
    CREDENTIALS_FORBIDDEN = "CREDENTIALS_FORBIDDEN"
    TRANSPORT_FIXTURE_MISS = "TRANSPORT_FIXTURE_MISS"
    RETRYABLE_STATUS_EXHAUSTED = "RETRYABLE_STATUS_EXHAUSTED"
    NON_RETRYABLE_HTTP_STATUS = "NON_RETRYABLE_HTTP_STATUS"
    OVERSIZE_BODY = "OVERSIZE_BODY"
    DECOMPRESSION_LIMIT = "DECOMPRESSION_LIMIT"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    HASH_MISMATCH = "HASH_MISMATCH"
    CHECKPOINT_REPLAY_MISMATCH = "CHECKPOINT_REPLAY_MISMATCH"


class FDAClientContractError(RuntimeError):
    def __init__(self, code: FDAClientErrorCode, detail: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {detail}")


HeaderPairs = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class FDARequest:
    method: str
    url: str
    headers: HeaderPairs = ()
    timeout_seconds: float = 10.0

    def header(self, name: str) -> str | None:
        needle = name.lower()
        for key, value in self.headers:
            if key.lower() == needle:
                return value
        return None


@dataclass(frozen=True, slots=True)
class FDAResponse:
    status_code: int
    headers: HeaderPairs = ()
    body: bytes = b""

    def header(self, name: str) -> str | None:
        needle = name.lower()
        for key, value in self.headers:
            if key.lower() == needle:
                return value
        return None


class FDATransport(Protocol):
    def send(self, request: FDARequest) -> FDAResponse:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class FDALiveClientConfig:
    contract_version: str = "fda-live-client-contract/v1.8"
    status: str = "disabled_dependency_injected_contract_only"
    network_implementation_allowed: bool = False
    scheduler_registration_allowed: bool = False
    production_persistence_allowed: bool = False
    credentials_allowed: bool = False
    requires_separate_explicit_authorization: bool = True
    allowed_hosts: tuple[str, ...] = (
        "api.fda.gov",
        "open.fda.gov",
        "www.fda.gov",
        "www.accessdata.fda.gov",
        "datadashboard.fda.gov",
    )
    allowed_media_types: tuple[str, ...] = (
        "application/json",
        "application/zip",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "text/html",
    )
    user_agent: str = "AguaLuz-FDA-disabled-client-contract/1.8"
    timeout_seconds: float = 10.0
    max_redirects: int = 3
    max_attempts: int = 3
    max_body_bytes: int = 2_000_000
    max_decompressed_bytes: int = 5_000_000
    max_decompression_ratio: int = 20
    max_requests_per_run: int = 10


@dataclass(frozen=True, slots=True)
class FDAReceipt:
    receipt_id: str
    provider: str
    source_id: str
    requested_url: str
    final_url: str
    method: str
    http_status: int
    retrieved_at: str
    media_type: str
    byte_count: int
    sha256: str
    retry_count: int
    request_fingerprint: str
    redactions: tuple[str, ...] = ()
    retry_plan: tuple[str, ...] = ()
    etag: str | None = None
    last_modified: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "provider": self.provider,
            "source_id": self.source_id,
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "method": self.method,
            "http_status": self.http_status,
            "retrieved_at": self.retrieved_at,
            "media_type": self.media_type,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "retry_count": self.retry_count,
            "request_fingerprint": self.request_fingerprint,
            "redactions": list(self.redactions),
            "retry_plan": list(self.retry_plan),
            "etag": self.etag,
            "last_modified": self.last_modified,
        }


@dataclass(frozen=True, slots=True)
class FDACheckpoint:
    source_profile_version: str
    request_fingerprint: str
    replay_state: str
    page_cursor: str | None
    etag: str | None
    last_modified: str | None
    last_accepted_raw_receipt_id: str
    last_accepted_raw_sha256: str
    normalizer_version: str
    retrieval_started_at_utc: str
    retrieval_completed_at_utc: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "source_profile_version": self.source_profile_version,
            "request_fingerprint": self.request_fingerprint,
            "replay_state": self.replay_state,
            "page_cursor": self.page_cursor,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "last_accepted_raw_receipt_id": self.last_accepted_raw_receipt_id,
            "last_accepted_raw_sha256": self.last_accepted_raw_sha256,
            "normalizer_version": self.normalizer_version,
            "retrieval_started_at_utc": self.retrieval_started_at_utc,
            "retrieval_completed_at_utc": self.retrieval_completed_at_utc,
        }


@dataclass(frozen=True, slots=True)
class FDAFetchResult:
    raw_bytes: bytes
    receipt: FDAReceipt
    checkpoint: FDACheckpoint


@dataclass(slots=True)
class OfflineFakeFDATransport:
    """Scripted transport for contract tests; it performs no socket I/O."""

    _responses: dict[str, list[FDAResponse]]
    requests: list[FDARequest] = field(default_factory=list)

    @classmethod
    def from_fixture(cls, fixture: Mapping[str, object]) -> OfflineFakeFDATransport:
        responses: dict[str, list[FDAResponse]] = {}
        for entry in fixture["responses"]:  # type: ignore[index]
            record = dict(entry)  # type: ignore[arg-type]
            method = str(record.get("method", "GET")).upper()
            url = str(record["url"])
            sequence = []
            for item in record["sequence"]:  # type: ignore[index]
                response = dict(item)
                headers = _headers_from_mapping(response.get("headers", {}))
                body = _body_from_fixture(response)
                sequence.append(FDAResponse(int(response["status_code"]), headers, body))
            responses[f"{method} {url}"] = sequence
        return cls(responses)

    @property
    def request_count(self) -> int:
        return len(self.requests)

    def send(self, request: FDARequest) -> FDAResponse:
        self.requests.append(request)
        key = f"{request.method.upper()} {request.url}"
        if key not in self._responses:
            raise FDAClientContractError(
                FDAClientErrorCode.TRANSPORT_FIXTURE_MISS,
                f"no offline response fixture for {request.method.upper()} request",
            )
        sequence = self._responses[key]
        if len(sequence) > 1:
            return sequence.pop(0)
        return sequence[0]


class DisabledFDALiveClient:
    def __init__(
        self,
        transport: FDATransport | None = None,
        *,
        config: FDALiveClientConfig | None = None,
        enabled: bool = False,
        secret_sentinels: Sequence[str] = (),
    ) -> None:
        self._transport = transport
        self._config = config or FDALiveClientConfig()
        self._enabled = enabled
        self._secret_sentinels = tuple(value for value in secret_sentinels if value)
        self._request_count = 0

    @property
    def config(self) -> FDALiveClientConfig:
        return self._config

    def get(
        self,
        source_id: str,
        url: str,
        *,
        expected_sha256: str | None = None,
        normalizer_version: str = "not-normalized",
    ) -> FDAFetchResult:
        self._require_enabled()
        self._require_transport()
        start = _utc_now()
        requested_url, redactions = self._redact_url(url)
        current_url = url
        retry_count = 0
        redirect_count = 0
        retry_plan: list[str] = []

        while True:
            self._validate_url(current_url)
            self._reject_real_credentials(current_url)
            if self._request_count >= self._config.max_requests_per_run:
                raise FDAClientContractError(
                    FDAClientErrorCode.REQUEST_BUDGET_EXHAUSTED,
                    "run-level request budget exhausted",
                )
            self._request_count += 1
            response = self._transport.send(self._build_request(current_url))  # type: ignore[union-attr]

            if response.status_code in {301, 302, 303, 307, 308}:
                redirect_count += 1
                if redirect_count > self._config.max_redirects:
                    raise FDAClientContractError(
                        FDAClientErrorCode.REDIRECT_LIMIT_EXCEEDED,
                        "redirect count exceeded contract maximum",
                    )
                current_url = self._redirect_target(current_url, response)
                continue

            if self._should_retry(response):
                if retry_count >= self._config.max_attempts - 1:
                    raise FDAClientContractError(
                        FDAClientErrorCode.RETRYABLE_STATUS_EXHAUSTED,
                        f"status {response.status_code} remained retryable after budget",
                    )
                retry_plan.append(self._retry_plan_entry(response, retry_count))
                retry_count += 1
                continue

            if 400 <= response.status_code < 500:
                raise FDAClientContractError(
                    FDAClientErrorCode.NON_RETRYABLE_HTTP_STATUS,
                    f"status {response.status_code} is not retryable",
                )

            media_type = self._media_type(response)
            raw = self._bounded_body(response)
            digest = hashlib.sha256(raw).hexdigest()
            if expected_sha256 and digest != expected_sha256:
                raise FDAClientContractError(
                    FDAClientErrorCode.HASH_MISMATCH,
                    "raw response SHA-256 did not match expected replay hash",
                )
            final_url, final_redactions = self._redact_url(current_url)
            redaction_report = tuple(sorted(set(redactions + final_redactions)))
            completed = _utc_now()
            fingerprint = self._fingerprint(source_id, "GET", requested_url)
            receipt = FDAReceipt(
                receipt_id=f"AYL_FDA_LIVE_RCPT_{digest[:24]}",
                provider="FDA",
                source_id=source_id,
                requested_url=requested_url,
                final_url=final_url,
                method="GET",
                http_status=response.status_code,
                retrieved_at=completed,
                media_type=media_type,
                byte_count=len(raw),
                sha256=digest,
                retry_count=retry_count,
                request_fingerprint=fingerprint,
                redactions=redaction_report,
                retry_plan=tuple(retry_plan),
                etag=response.header("etag"),
                last_modified=response.header("last-modified"),
            )
            checkpoint = FDACheckpoint(
                source_profile_version=self._config.contract_version,
                request_fingerprint=fingerprint,
                replay_state="terminal",
                page_cursor=None,
                etag=response.header("etag"),
                last_modified=response.header("last-modified"),
                last_accepted_raw_receipt_id=receipt.receipt_id,
                last_accepted_raw_sha256=digest,
                normalizer_version=normalizer_version,
                retrieval_started_at_utc=start,
                retrieval_completed_at_utc=completed,
            )
            return FDAFetchResult(raw, receipt, checkpoint)

    def replay_from_checkpoint(
        self,
        source_id: str,
        url: str,
        checkpoint: FDACheckpoint,
        *,
        normalizer_version: str = "not-normalized",
    ) -> FDAFetchResult:
        requested_url, _ = self._redact_url(url)
        fingerprint = self._fingerprint(source_id, "GET", requested_url)
        if fingerprint != checkpoint.request_fingerprint:
            raise FDAClientContractError(
                FDAClientErrorCode.CHECKPOINT_REPLAY_MISMATCH,
                "checkpoint request fingerprint does not match replay request",
            )
        return self.get(
            source_id,
            url,
            expected_sha256=checkpoint.last_accepted_raw_sha256,
            normalizer_version=normalizer_version,
        )

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise FDAClientContractError(
                FDAClientErrorCode.CLIENT_DISABLED,
                "FDA live client contract is disabled by default",
            )

    def _require_transport(self) -> None:
        if self._transport is None:
            raise FDAClientContractError(
                FDAClientErrorCode.TRANSPORT_REQUIRED,
                "dependency-injected transport is required; no default HTTP transport exists",
            )

    def _build_request(self, url: str) -> FDARequest:
        return FDARequest(
            method="GET",
            url=url,
            headers=(("user-agent", self._config.user_agent),),
            timeout_seconds=self._config.timeout_seconds,
        )

    def _validate_url(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https":
            raise FDAClientContractError(
                FDAClientErrorCode.HTTPS_REQUIRED,
                "FDA acquisition contract permits HTTPS URLs only",
            )
        host = (parsed.hostname or "").lower()
        if host not in self._config.allowed_hosts:
            raise FDAClientContractError(
                FDAClientErrorCode.HOST_NOT_ALLOWED,
                f"host {host or '<missing>'} is not in the exact FDA allow-list",
            )

    def _redirect_target(self, current_url: str, response: FDAResponse) -> str:
        location = response.header("location")
        if not location:
            raise FDAClientContractError(
                FDAClientErrorCode.REDIRECT_ESCAPE,
                "redirect response omitted Location header",
            )
        if location.startswith("/"):
            current = urlsplit(current_url)
            location = urlunsplit((current.scheme, current.netloc, location, "", ""))
        parsed = urlsplit(location)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in self._config.allowed_hosts:
            raise FDAClientContractError(
                FDAClientErrorCode.REDIRECT_ESCAPE,
                "redirect target escaped the exact FDA host allow-list",
            )
        return location

    def _should_retry(self, response: FDAResponse) -> bool:
        return response.status_code in {408, 429} or 500 <= response.status_code <= 599

    @staticmethod
    def _retry_plan_entry(response: FDAResponse, retry_count: int) -> str:
        retry_after = response.header("retry-after")
        if response.status_code == 429 and retry_after:
            return f"retry-after:{retry_after}"
        return f"backoff:{0.5 * (2**retry_count):.1f}"

    def _media_type(self, response: FDAResponse) -> str:
        media_type = (response.header("content-type") or "application/octet-stream").split(";")[0]
        media_type = media_type.strip().lower()
        if media_type not in self._config.allowed_media_types:
            raise FDAClientContractError(
                FDAClientErrorCode.UNSUPPORTED_MEDIA_TYPE,
                f"media type {media_type} is not allowed for FDA contract ingestion",
            )
        return media_type

    def _bounded_body(self, response: FDAResponse) -> bytes:
        body = response.body
        if len(body) > self._config.max_body_bytes:
            raise FDAClientContractError(
                FDAClientErrorCode.OVERSIZE_BODY,
                "compressed or raw body exceeded byte budget",
            )
        if (response.header("content-encoding") or "").lower() == "gzip":
            decompressed = gzip.decompress(body)
            ratio = len(decompressed) / max(len(body), 1)
            if (
                len(decompressed) > self._config.max_decompressed_bytes
                or ratio > self._config.max_decompression_ratio
            ):
                raise FDAClientContractError(
                    FDAClientErrorCode.DECOMPRESSION_LIMIT,
                    "decompressed response exceeded byte or ratio budget",
                )
            body = decompressed
        if len(body) > self._config.max_body_bytes:
            raise FDAClientContractError(
                FDAClientErrorCode.OVERSIZE_BODY,
                "response body exceeded byte budget",
            )
        return body

    def _redact_url(self, url: str) -> tuple[str, tuple[str, ...]]:
        parsed = urlsplit(url)
        redactions: list[str] = []
        safe_query = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() in {"api_key", "apikey", "key", "token"}:
                safe_query.append((key, "REDACTED"))
                redactions.append(f"query:{key}")
            else:
                safe_query.append((key, value))
        safe_url = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(safe_query), parsed.fragment)
        )
        for index, sentinel in enumerate(self._secret_sentinels, start=1):
            if sentinel in safe_url:
                safe_url = safe_url.replace(sentinel, f"REDACTED_SENTINEL_{index}")
                redactions.append(f"sentinel:{index}")
        return safe_url, tuple(redactions)

    def _reject_real_credentials(self, url: str) -> None:
        for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True):
            if key.lower() in {"api_key", "apikey", "key", "token"} and value not in self._secret_sentinels:
                raise FDAClientContractError(
                    FDAClientErrorCode.CREDENTIALS_FORBIDDEN,
                    "real credentials are not accepted by this disabled contract",
                )

    @staticmethod
    def _fingerprint(source_id: str, method: str, requested_url: str) -> str:
        material = json.dumps(
            {"source_id": source_id, "method": method.upper(), "url": requested_url},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()


def _headers_from_mapping(headers: object) -> HeaderPairs:
    if not isinstance(headers, Mapping):
        return ()
    return tuple((str(key).lower(), str(value)) for key, value in headers.items())


def _body_from_fixture(response: Mapping[str, object]) -> bytes:
    if "body_base64" in response:
        return base64.b64decode(str(response["body_base64"]))
    return str(response.get("body_text", "")).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
