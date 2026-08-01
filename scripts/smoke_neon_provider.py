#!/usr/bin/env python3
"""Run one bounded, non-persisting NEON provider health check.

The credential is read only by the provider adapter from NEON_API_TOKEN. This
script never prints environment values or request headers.
"""

from __future__ import annotations

import json
import os
import sys

from server.backend.environmental_providers import NEON_PR_SITES, poll_provider


def main() -> int:
    if not os.getenv("NEON_API_TOKEN"):
        print("BLOCKED: NEON_API_TOKEN is not configured", file=sys.stderr)
        return 2

    os.environ["AGUAYLUZ_EXTERNAL_POLLING_ENABLED"] = "true"
    result = poll_provider("neon", timeout=20.0)

    safe_result = {
        key: value
        for key, value in result.items()
        if key
        in {
            "provider",
            "status",
            "checked_at",
            "http_status",
            "payload_bytes",
            "sha256",
            "error_type",
            "reason",
        }
    }
    receipt = {
        "schema_version": "aguayluz.neon-live-smoke/v1",
        "persisted": False,
        "notifications_enabled": False,
        "certified_series_promoted": False,
        "site_codes": sorted(site["site_code"] for site in NEON_PR_SITES),
        "result": safe_result,
    }
    print(json.dumps(receipt, sort_keys=True))

    if receipt["site_codes"] != ["CUPE", "GUAN", "GUIL", "LAJA"]:
        print("FAIL: Puerto Rico NEON site registry changed", file=sys.stderr)
        return 3
    if result.get("provider") != "neon" or result.get("status") != "ok":
        print("FAIL: bounded NEON provider smoke did not succeed", file=sys.stderr)
        return 1
    if result.get("http_status") != 200:
        print("FAIL: NEON returned a non-200 status", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
