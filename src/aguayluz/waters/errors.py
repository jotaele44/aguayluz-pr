"""Typed error hierarchy for the WATERS client."""

from __future__ import annotations


class WatersError(Exception):
    """Base class for all WATERS client errors."""


class AuthError(WatersError):
    """Missing or rejected api.data.gov key."""


class RateLimitExceeded(WatersError):
    """HTTP 429 OVER_RATE_LIMIT after exhausting all retries."""

    def __init__(self, message: str, attempts: int, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.retry_after = retry_after


class WatersServerError(WatersError):
    """Non-retryable 5xx from the gateway or upstream WATERS service."""

    def __init__(self, message: str, status_code: int, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
