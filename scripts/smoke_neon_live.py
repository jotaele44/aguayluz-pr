#!/usr/bin/env python3
"""Bounded, secret-safe live smoke for the NSF NEON Puerto Rico integration."""
from __future__ import annotations

import json
import os

import httpx

from aguayluz.neon.client import TOKEN_HEADER, USER_AGENT, resolve_token
from aguayluz.neon.endpoints import DEFAULT_BASE_URL
from aguayluz.neon.mapping import PR_DOMAIN_CODE, PR_SITE_CODES

EXPECTED_CODES = {"CUPE", "GUAN", "GUIL", "LAJA"}


def main() -> int:
    token = resolve_token()
    if not token:
        raise SystemExit("FAIL: NEON_API_TOKEN is not configured")

    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        TOKEN_HEADER: token,
    }
    response = httpx.get(f"{DEFAULT_BASE_URL}/sites", headers=headers, timeout=60.0)
    if response.status_code != 200:
        raise SystemExit(f"FAIL: NEON /sites returned HTTP {response.status_code}")

    document = response.json()
    rows = document.get("data") or []
    observed_codes = {
        str(row.get("siteCode"))
        for row in rows
        if isinstance(row, dict) and row.get("domainCode") == PR_DOMAIN_CODE
    }

    if PR_SITE_CODES != EXPECTED_CODES:
        raise SystemExit("FAIL: canonical Puerto Rico NEON registry changed")
    if observed_codes != EXPECTED_CODES:
        raise SystemExit("FAIL: live Puerto Rico NEON site denominator does not match canonical registry")

    receipt = {
        "schema_version": "aguayluz.neon-live-smoke/v1",
        "provider": "neon",
        "status": "ok",
        "http_status": response.status_code,
        "authenticated": True,
        "site_codes": sorted(observed_codes),
        "persisted": False,
        "notifications_enabled": False,
        "certified_series_promoted": False,
    }
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
