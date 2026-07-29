"""HTTP client for the NEON (NSF National Ecological Observatory Network) API v0.

Auth: an optional NEON API token.
  - Resolution order: explicit arg -> $NEON_API_TOKEN -> $NEON_API_KEY -> None.
  - Sent as the `X-API-Token` header. **Not** `Authorization: Bearer` — NEON does
    not accept a bearer token, and sending one leaves you effectively anonymous.
  - `None` is a first-class supported mode, unlike :class:`WatersClient` which
    raises when no key is found: NEON's metadata endpoints answer 200 anonymously.
    Only `/data/...` is gated.

403 disambiguation — the behaviour that matters most here. NEON returns 403 both
for "this endpoint needs a token" and for "your token is bad", and an *invalid*
token turns an otherwise-200 anonymous request into a 403. So:
  - 401/403 with a token   -> NeonAuthError     (rotate/fix the credential)
  - 403 with no token      -> NeonAccessDenied  (endpoint is gated)
Never silently retry a rejected token anonymously: that would hide a rotated
credential behind a 200 and a 50x-lower rate limit.

Retry: 429 and 5xx are retried up to `max_retries` times. Sleep honors
`Retry-After` when present; otherwise exponential backoff 1s / 2s / 4s with jitter.

Observability: emits `X-RateLimit-Remaining` to the standard logger after every
response. NEON allows 200 requests/hour anonymously (a token raises the ceiling),
which is low enough that a chatty caller can exhaust it inside one refresh run.

The token is never logged, never included in `repr()`, and never serialized.
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any

import httpx

from .endpoints import API_VERSION, DEFAULT_BASE_URL, is_gated
from .errors import (
    NeonAccessDenied,
    NeonAuthError,
    NeonRateLimitExceeded,
    NeonServerError,
)

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SCHEDULE_S: tuple[float, ...] = (1.0, 2.0, 4.0)
USER_AGENT = "aguayluz-pr/0.1 (+https://github.com/jotaele44/aguayluz-pr)"

#: Header NEON authenticates on. Documented explicitly because `Authorization:
#: Bearer` is the intuitive-but-wrong choice and fails open (silently anonymous).
TOKEN_HEADER = "X-API-Token"

#: Environment variables consulted for the token, in order.
TOKEN_ENV_VARS: tuple[str, ...] = ("NEON_API_TOKEN", "NEON_API_KEY")

#: Warn when the hourly quota drops below this. Anonymous ceiling is 200/hr.
RATE_LIMIT_WARN_BELOW = 25

logger = logging.getLogger("aguayluz.neon")


def resolve_token(explicit: str | None = None) -> str | None:
    """Return the NEON API token, or ``None`` for anonymous access.

    Anonymous is a valid mode — every metadata endpoint this repo reads works
    without a credential — so this returns ``None`` instead of raising.
    """
    if explicit:
        return explicit
    for var in TOKEN_ENV_VARS:
        val = os.environ.get(var)
        if val:
            return val
    return None


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _rate_limit_remaining(response: httpx.Response) -> int | None:
    raw = response.headers.get("X-RateLimit-Remaining")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class NeonClient:
    """Synchronous HTTP client for data.neonscience.org/api/v0.

    Use as a context manager when possible::

        with NeonClient() as c:
            doc = c.get(endpoints.site("CUPE"))
    """

    def __init__(
        self,
        token: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_schedule_s: tuple[float, ...] = DEFAULT_BACKOFF_SCHEDULE_S,
        sleep_fn=time.sleep,
        client: httpx.Client | None = None,
    ) -> None:
        self._token = resolve_token(token)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_schedule_s = backoff_schedule_s
        self.api_version = API_VERSION
        self._sleep = sleep_fn
        #: Last observed X-RateLimit-Remaining, for health reporting.
        self.rate_limit_remaining: int | None = None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._owns_client = client is None

    # ------------------------------------------------------------------
    # Token handling — deliberately no public accessor for the value.
    # ------------------------------------------------------------------

    @property
    def has_token(self) -> bool:
        """True when a token will be sent. The value itself is never exposed."""
        return self._token is not None

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"NeonClient(base_url={self.base_url!r}, has_token={self.has_token})"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> NeonClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Core HTTP
    # ------------------------------------------------------------------

    def _backoff(self, attempt: int) -> float:
        if attempt < len(self.backoff_schedule_s):
            base = self.backoff_schedule_s[attempt]
        else:
            base = self.backoff_schedule_s[-1] * (2 ** (attempt - len(self.backoff_schedule_s) + 1))
        return base + random.random() * 0.25  # noqa: S311 — jitter, not security

    def _auth_headers(self, headers: dict[str, str]) -> dict[str, str]:
        if self._token is None:
            return headers
        return {**headers, TOKEN_HEADER: self._token}

    def _log_rate_limit(self, response: httpx.Response) -> None:
        remaining = _rate_limit_remaining(response)
        if remaining is None:
            return
        self.rate_limit_remaining = remaining
        if remaining < RATE_LIMIT_WARN_BELOW:
            logger.warning("NEON rate limit low: %s remaining", remaining)
        else:
            logger.debug("NEON rate limit remaining: %s", remaining)

    def _raise_for_auth(self, response: httpx.Response, path: str) -> None:
        """Turn a 401/403 into the exception that names the right operator action."""
        body = (response.text or "")[:300]
        if self.has_token:
            raise NeonAuthError(
                f"NEON rejected the API token (HTTP {response.status_code}) for {path}. "
                f"Verify NEON_API_TOKEN is current — NEON returns 403 for an invalid or "
                f"expired token even on endpoints that answer 200 anonymously. Body: {body}"
            )
        gated_hint = (
            " This endpoint requires a NEON API token; the metadata endpoints "
            "(/sites, /products, /releases) do not."
            if is_gated(path)
            else ""
        )
        raise NeonAccessDenied(
            f"NEON denied anonymous access (HTTP {response.status_code}) to {path}."
            f"{gated_hint} Body: {body}"
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute one HTTP call with auth + retry, return the parsed JSON dict.

        Raises :class:`NeonAuthError` when a token is present and rejected,
        :class:`NeonAccessDenied` on an anonymous 403, :class:`NeonRateLimitExceeded`
        when 429 persists past ``max_retries``, :class:`NeonServerError` for a
        persistent 5xx, and propagates ``httpx.HTTPStatusError`` for other 4xx.
        """
        url = f"{self.base_url}{path}"
        params = dict(params or {})
        headers = self._auth_headers(dict(extra_headers or {}))

        last_response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            response = self._client.request(method, url, params=params, headers=headers)
            last_response = response
            self._log_rate_limit(response)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise NeonRateLimitExceeded(
                        f"NEON rate limit exceeded after {attempt + 1} attempt(s)",
                        attempts=attempt + 1,
                        retry_after=_parse_retry_after(response),
                    )
                sleep_s = _parse_retry_after(response) or self._backoff(attempt)
                logger.warning(
                    "NEON 429; sleeping %.2fs before retry %d/%d",
                    sleep_s, attempt + 1, self.max_retries,
                )
                self._sleep(sleep_s)
                continue

            if response.status_code in (401, 403):
                self._raise_for_auth(response, path)

            if 500 <= response.status_code < 600:
                if attempt >= self.max_retries:
                    raise NeonServerError(
                        f"NEON server error (HTTP {response.status_code}) for {path}",
                        status_code=response.status_code,
                        body=(response.text or "")[:1000],
                    )
                sleep_s = self._backoff(attempt)
                logger.warning(
                    "NEON %d; sleeping %.2fs before retry %d/%d",
                    response.status_code, sleep_s, attempt + 1, self.max_retries,
                )
                self._sleep(sleep_s)
                continue

            response.raise_for_status()

        # Defensive — the loop exits via return/raise above.
        assert last_response is not None  # noqa: S101
        raise NeonServerError(
            "NEON client exhausted retry loop unexpectedly",
            status_code=last_response.status_code,
            body=(last_response.text or "")[:1000],
        )

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("GET", path, params=params)

    def get_data(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET returning the NEON envelope's ``data`` member (the common case)."""
        return self.get(path, params=params).get("data")
