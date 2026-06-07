#!/usr/bin/env python3
"""Post a drift alert to a Slack-compatible webhook.

Used by the M23 monitoring workflows (`live-corpus.yml`, `oas-monitor.yml`)
when `--baseline-check` or `--check` exits non-zero. The webhook URL is read
from `$SLACK_WEBHOOK_URL` so the value never appears in the workflow file or
the script CLI — passing it via env: in the workflow keeps it inside the
GitHub Actions secret-masking boundary.

Without `$SLACK_WEBHOOK_URL` set the script logs and exits 0 so it doesn't
break local runs that don't have a webhook configured.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx

DEFAULT_TIMEOUT_S = 10.0

_SEVERITY_COLOR = {
    "info":     "#36a64f",   # green
    "warn":     "#f2c744",   # yellow
    "critical": "#d50200",   # red
}


def build_payload(*, title: str, severity: str, body: str) -> dict[str, Any]:
    """Slack-incoming-webhook compatible JSON shape."""
    severity = severity.lower()
    if severity not in _SEVERITY_COLOR:
        severity = "info"
    return {
        "text": f"[{severity.upper()}] {title}",
        "attachments": [
            {
                "color": _SEVERITY_COLOR[severity],
                "fallback": body[:200],
                "text": body,
                "footer": "aguayluz-pr / M23 drift monitor",
            }
        ],
    }


def post_to_webhook(
    *,
    webhook_url: str,
    payload: dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT_S,
) -> int:
    """Post the payload; return HTTP status. Caller decides what to do on failure."""
    response = httpx.post(webhook_url, json=payload, timeout=timeout)
    return response.status_code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Post a drift alert to a Slack webhook")
    p.add_argument("--title", required=True)
    p.add_argument("--severity", default="warn", choices=["info", "warn", "critical"])
    p.add_argument("--body", required=True)
    p.add_argument("--webhook-env", default="SLACK_WEBHOOK_URL",
                   help="Env var holding the webhook URL (default: SLACK_WEBHOOK_URL)")
    p.add_argument("--print", action="store_true",
                   help="Print the payload to stdout (useful for testing without posting)")
    args = p.parse_args(argv)

    payload = build_payload(title=args.title, severity=args.severity, body=args.body)

    if args.print:
        print(json.dumps(payload, indent=2))
        return 0

    url = os.environ.get(args.webhook_env)
    if not url:
        # Local-friendly: don't fail when no webhook is configured.
        print(f"notify_drift: ${args.webhook_env} not set; skipping (would post: {args.title})")
        return 0

    status = post_to_webhook(webhook_url=url, payload=payload)
    if 200 <= status < 300:
        print(f"notify_drift: posted ({status})")
        return 0
    print(f"notify_drift: webhook returned HTTP {status}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
