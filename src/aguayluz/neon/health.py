"""NEON provider health check.

Answers one question before a refresh run commits to anything: is NEON reachable,
and is the credential (if any) actually working? Probes ``/sites`` — the cheapest
open endpoint — and reports latency plus the remaining hourly quota.

:func:`check_health` **never raises**. A provider being down must degrade
AguaYLuz to a warning, not abort a refresh that still has USGS, NOAA and EPA
steps to run. Every failure mode becomes a populated ``error`` string instead.

``authenticated`` is true only when a token was sent *and* accepted. It is false
both for anonymous access (fine — the metadata endpoints are open) and for a
rejected token (not fine); ``token_present`` and ``error`` distinguish the two.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from .client import NeonClient
from .endpoints import SITES
from .errors import NeonAccessDenied, NeonAuthError, NeonError
from .mapping import PR_DOMAIN_CODE

PROVIDER = "NEON"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def check_health(
    client: NeonClient | None = None,
    *,
    now_fn=_utc_now_iso,
    timer=time.monotonic,
) -> dict[str, Any]:
    """Probe the NEON API and return a health record. Never raises.

    Returns a dict with ``provider``, ``reachable``, ``authenticated``,
    ``token_present``, ``latency_ms``, ``checked_at``, ``rate_limit_remaining``,
    ``pr_site_count``, ``api_version`` and ``error``.
    """
    owns_client = client is None
    record: dict[str, Any] = {
        "provider": PROVIDER,
        "reachable": False,
        "authenticated": False,
        "token_present": False,
        "latency_ms": None,
        "checked_at": now_fn(),
        "rate_limit_remaining": None,
        "pr_site_count": None,
        "api_version": None,
        "error": None,
    }

    try:
        client = client or NeonClient()
    except Exception as exc:  # noqa: BLE001 — health must never raise
        record["error"] = f"client construction failed: {exc}"
        return record

    record["token_present"] = client.has_token
    record["api_version"] = client.api_version

    started = timer()
    try:
        doc = client.get(SITES)
    except NeonAuthError as exc:
        record["latency_ms"] = int((timer() - started) * 1000)
        # Reached NEON — it answered, it just rejected the credential.
        record["reachable"] = True
        record["error"] = f"token rejected: {exc}"
        return record
    except NeonAccessDenied as exc:
        record["latency_ms"] = int((timer() - started) * 1000)
        record["reachable"] = True
        record["error"] = f"access denied: {exc}"
        return record
    except NeonError as exc:
        record["latency_ms"] = int((timer() - started) * 1000)
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record
    except Exception as exc:  # noqa: BLE001 — transport errors, bad JSON, anything
        record["latency_ms"] = int((timer() - started) * 1000)
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record
    finally:
        if owns_client:
            client.close()

    record["latency_ms"] = int((timer() - started) * 1000)
    record["reachable"] = True
    # A token that survived a real request is a working token.
    record["authenticated"] = client.has_token
    record["rate_limit_remaining"] = client.rate_limit_remaining

    sites = doc.get("data") or []
    record["pr_site_count"] = sum(
        1 for s in sites if isinstance(s, dict) and s.get("domainCode") == PR_DOMAIN_CODE
    )
    return record
