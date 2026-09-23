"""Shared HTTP retry helper for keyless ingest scripts.

``src/aguayluz/neon/client.py`` is the one HTTP client in this repo that
retries transient failures (429/5xx, connect/timeout) with exponential
backoff and jitter, honoring ``Retry-After`` when present. Every other
ingest script (USGS, NWS, NHC, NOAA tides, ...) does a single
``httpx.get(...)`` + ``raise_for_status()`` with no retry, so a transient
timeout or 5xx from a public government API — common during a hazard event,
when traffic to these same APIs spikes — fails the whole ingest step
outright. This module extracts that retry behavior so it can be reused
without pulling in NEON's auth-specific error taxonomy, which doesn't apply
to keyless endpoints.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import httpx

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SCHEDULE_S: tuple[float, ...] = (1.0, 2.0, 4.0)

#: 429 and 5xx are treated as transient; every other status is returned
#: as-is for the caller's own raise_for_status() to handle.
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

logger = logging.getLogger("aguayluz.http_retry")


def _backoff(attempt: int, schedule: tuple[float, ...]) -> float:
    if attempt < len(schedule):
        base = schedule[attempt]
    else:
        base = schedule[-1] * (2 ** (attempt - len(schedule) + 1))
    return base + random.random() * 0.25  # noqa: S311 — jitter, not security


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_schedule: tuple[float, ...] = DEFAULT_BACKOFF_SCHEDULE_S,
    sleep_fn: Any = time.sleep,
) -> httpx.Response:
    """Execute one HTTP call via ``client``, retrying 429/5xx and transport errors.

    Returns the final ``httpx.Response`` (including a non-2xx one once retries
    are exhausted — the caller still calls ``raise_for_status()``), or
    re-raises the last ``httpx.TransportError``/``httpx.TimeoutException``.
    """
    response: httpx.Response | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.request(method, url, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt >= max_retries:
                raise
            sleep_s = _backoff(attempt, backoff_schedule)
            logger.warning(
                "%s %s failed (%s); retrying %d/%d in %.2fs",
                method, url, exc, attempt + 1, max_retries, sleep_s,
            )
            sleep_fn(sleep_s)
            continue

        if response.status_code not in RETRY_STATUS_CODES or attempt >= max_retries:
            return response
        sleep_s = _parse_retry_after(response) or _backoff(attempt, backoff_schedule)
        logger.warning(
            "%s %s -> HTTP %d; retrying %d/%d in %.2fs",
            method, url, response.status_code, attempt + 1, max_retries, sleep_s,
        )
        sleep_fn(sleep_s)

    assert response is not None  # noqa: S101 — loop always sets or raises
    return response


def get_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
    follow_redirects: bool = True,
    client: httpx.Client | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_schedule: tuple[float, ...] = DEFAULT_BACKOFF_SCHEDULE_S,
    sleep_fn: Any = time.sleep,
) -> httpx.Response:
    """Drop-in replacement for ``httpx.get(...)`` with retry on 429/5xx/timeout.

    Opens a short-lived client when ``client`` isn't supplied, mirroring
    ``httpx.get``'s convenience-function behavior.
    """
    owns_client = client is None
    active = client or httpx.Client(timeout=timeout, follow_redirects=follow_redirects)
    try:
        return request_with_retry(
            active, "GET", url,
            params=params, headers=headers,
            max_retries=max_retries, backoff_schedule=backoff_schedule, sleep_fn=sleep_fn,
        )
    finally:
        if owns_client:
            active.close()
