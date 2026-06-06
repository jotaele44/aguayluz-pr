"""HTTP client for the U.S. EPA Office of Water WATERS Services API.

Auth: api.data.gov key.
  - Resolution order: explicit arg → $EPA_WATERS_API_KEY → $API_DATA_GOV_KEY → AuthError.
  - Sent as `X-Api-Key` header (preferred; cacheable + clean URLs).
  - `api_key` query-param fallback can be forced via `auth_mode="query"`.

Retry: on HTTP 429 with body containing `OVER_RATE_LIMIT`, retry up to
`max_retries` times. Sleep honors `Retry-After` when present; otherwise
exponential backoff 1s / 2s / 4s with optional jitter.

Observability: emits `X-RateLimit-Remaining` to the standard logger after every
response so production scripts can alert before exhaustion.
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Literal

import httpx

from .errors import AuthError, RateLimitExceeded, WatersServerError

DEFAULT_BASE_URL = "https://api.epa.gov/waters"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SCHEDULE_S: tuple[float, ...] = (1.0, 2.0, 4.0)
USER_AGENT = "aguayluz-pr/0.1 (+https://github.com/jotaele44/aguayluz-pr)"

AuthMode = Literal["header", "query"]

logger = logging.getLogger("aguayluz.waters")


def _resolve_api_key(explicit: str | None) -> str:
    if explicit:
        return explicit
    for var in ("EPA_WATERS_API_KEY", "API_DATA_GOV_KEY"):
        val = os.environ.get(var)
        if val:
            return val
    raise AuthError(
        "No API key found. Set EPA_WATERS_API_KEY or API_DATA_GOV_KEY, "
        "or pass api_key=... to WatersClient. Free keys: https://api.data.gov/signup/"
    )


def _is_rate_limited(response: httpx.Response) -> bool:
    if response.status_code != 429:
        return False
    body = response.text or ""
    return "OVER_RATE_LIMIT" in body or "rate limit" in body.lower()


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class WatersClient:
    """Synchronous HTTP client for api.epa.gov/waters.

    Use as a context manager when possible:
        with WatersClient() as c:
            data = c.get("/v1/pointindexing", params={"pgeometry": "POINT(-66.232 18.388)", "output": "JSON"})
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_schedule_s: tuple[float, ...] = DEFAULT_BACKOFF_SCHEDULE_S,
        auth_mode: AuthMode = "header",
        sleep_fn=time.sleep,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = _resolve_api_key(api_key)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_schedule_s = backoff_schedule_s
        self.auth_mode: AuthMode = auth_mode
        self._sleep = sleep_fn
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._owns_client = client is None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> WatersClient:
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

    def _apply_auth(
        self,
        headers: dict[str, str],
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        if self.auth_mode == "header":
            headers = {**headers, "X-Api-Key": self.api_key}
        else:
            params = {**params, "api_key": self.api_key}
        return headers, params

    def _log_rate_limit(self, response: httpx.Response) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            try:
                if int(remaining) < 50:
                    logger.warning("WATERS rate limit low: %s remaining", remaining)
                else:
                    logger.debug("WATERS rate limit remaining: %s", remaining)
            except ValueError:
                logger.debug("WATERS rate limit header: %s", remaining)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute one HTTP call with auth + retry, return parsed JSON dict.

        Raises AuthError if the key is missing or rejected, RateLimitExceeded
        if 429 persists past max_retries, WatersServerError for non-retryable
        5xx, and propagates httpx.HTTPStatusError for other 4xx.
        """
        url = f"{self.base_url}{path}"
        params = dict(params or {})
        headers = dict(extra_headers or {})
        headers, params = self._apply_auth(headers, params)
        # WATERS always speaks JSON when asked.
        params.setdefault("output", "JSON")

        last_response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            response = self._client.request(method, url, params=params, json=json_body, headers=headers)
            last_response = response
            self._log_rate_limit(response)

            if response.status_code == 200:
                return response.json()

            if _is_rate_limited(response):
                if attempt >= self.max_retries:
                    retry_after = _parse_retry_after(response)
                    raise RateLimitExceeded(
                        f"WATERS rate limit exceeded after {attempt + 1} attempt(s)",
                        attempts=attempt + 1,
                        retry_after=retry_after,
                    )
                sleep_s = _parse_retry_after(response) or self._backoff(attempt)
                logger.warning("WATERS 429; sleeping %.2fs before retry %d/%d", sleep_s, attempt + 1, self.max_retries)
                self._sleep(sleep_s)
                continue

            if response.status_code == 401 or response.status_code == 403:
                raise AuthError(
                    f"WATERS rejected api key (HTTP {response.status_code}): "
                    f"{response.text[:300]}"
                )

            if 500 <= response.status_code < 600:
                raise WatersServerError(
                    f"WATERS server error (HTTP {response.status_code})",
                    status_code=response.status_code,
                    body=response.text[:1000],
                )

            response.raise_for_status()

        # Defensive — loop exits via return/raise above.
        assert last_response is not None
        raise WatersServerError(
            "WATERS client exhausted retry loop unexpectedly",
            status_code=last_response.status_code,
            body=last_response.text[:1000],
        )

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("GET", path, params=params)

    def post(
        self,
        path: str,
        *,
        json_body: Any,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.request("POST", path, params=params, json_body=json_body)
