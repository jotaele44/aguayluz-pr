"""Typed error hierarchy for the NEON client.

Mirrors :mod:`aguayluz.waters.errors`, with one distinction that has no WATERS
analogue: NEON serves its metadata endpoints anonymously but gates the bulk
file-manifest endpoint, and it *also* rejects a bad token with the same 403. The
two cases need different operator action, so they get different exceptions —
:class:`NeonAuthError` means "fix your token", :class:`NeonAccessDenied` means
"this endpoint needs a token you do not have".
"""

from __future__ import annotations


class NeonError(Exception):
    """Base class for all NEON client errors."""


class NeonAuthError(NeonError):
    """A token WAS sent and NEON rejected it (HTTP 401/403).

    NEON returns 403 for an invalid or expired ``X-API-Token`` even on endpoints
    that answer 200 anonymously, so a bad token is strictly worse than no token.
    Never downgrade this to a silent anonymous retry — that would mask a rotated
    or mistyped credential behind a lower rate limit.
    """


class NeonAccessDenied(NeonError):
    """HTTP 403 with NO token present — the endpoint is credential-gated.

    Raised by the ``/data/{product}/{site}/{month}`` file-manifest endpoint, which
    returns ``{"error":{"status":403,"detail":"Access Denied"},"data":null}`` to
    anonymous callers while ``/sites``, ``/products`` and ``/releases`` answer 200.
    """


class NeonRateLimitExceeded(NeonError):
    """HTTP 429 after exhausting all retries."""

    def __init__(self, message: str, attempts: int, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.retry_after = retry_after


class NeonServerError(NeonError):
    """Non-retryable 5xx from the NEON API gateway."""

    def __init__(self, message: str, status_code: int, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
