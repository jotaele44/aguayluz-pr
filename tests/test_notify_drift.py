"""Tests for `scripts/notify_drift.py` (Slack webhook helper)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "notify_drift.py"

# Import the module directly so we can unit-test the helpers without subprocess.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import notify_drift  # type: ignore[import-not-found]  # noqa: E402

# ---------- payload shape ----------


def test_payload_uses_severity_color_critical():
    payload = notify_drift.build_payload(
        title="OAS shape drift", severity="critical", body="server_url changed",
    )
    assert payload["text"] == "[CRITICAL] OAS shape drift"
    assert payload["attachments"][0]["color"] == "#d50200"
    assert payload["attachments"][0]["text"] == "server_url changed"


def test_payload_uses_severity_color_warn():
    payload = notify_drift.build_payload(title="x", severity="warn", body="b")
    assert payload["attachments"][0]["color"] == "#f2c744"


def test_payload_uses_severity_color_info():
    payload = notify_drift.build_payload(title="x", severity="info", body="b")
    assert payload["attachments"][0]["color"] == "#36a64f"


def test_payload_falls_back_on_unknown_severity():
    payload = notify_drift.build_payload(title="x", severity="apocalyptic", body="b")
    assert payload["text"].startswith("[INFO]")
    assert payload["attachments"][0]["color"] == "#36a64f"


def test_payload_fallback_truncates_long_body():
    long_body = "x" * 500
    payload = notify_drift.build_payload(title="x", severity="warn", body=long_body)
    assert len(payload["attachments"][0]["fallback"]) == 200


# ---------- HTTP post ----------


def test_post_to_webhook_returns_status(httpx_mock):
    httpx_mock.add_response(method="POST", json={"ok": True}, status_code=200)
    status = notify_drift.post_to_webhook(
        webhook_url="https://hooks.example/webhook",
        payload={"text": "test"},
    )
    assert status == 200


def test_post_to_webhook_returns_4xx_status(httpx_mock):
    httpx_mock.add_response(method="POST", status_code=404, text="not found")
    status = notify_drift.post_to_webhook(
        webhook_url="https://hooks.example/webhook",
        payload={"text": "test"},
    )
    assert status == 404


# ---------- CLI ----------


def test_cli_print_mode_emits_json():
    proc = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--title", "test drift",
            "--severity", "warn",
            "--body", "body text",
            "--print",
        ],
        capture_output=True, text=True, check=False, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["text"] == "[WARN] test drift"


def test_cli_skips_when_webhook_not_set(monkeypatch):
    """Local-friendly: no webhook env → exit 0 with a skip message."""
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    exit_code = notify_drift.main([
        "--title", "x", "--severity", "warn", "--body", "b",
    ])
    assert exit_code == 0


def test_cli_returns_1_on_webhook_failure(httpx_mock, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/bad")
    httpx_mock.add_response(method="POST", status_code=500)
    exit_code = notify_drift.main([
        "--title", "x", "--severity", "critical", "--body", "b",
    ])
    assert exit_code == 1


def test_cli_returns_0_on_webhook_success(httpx_mock, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/good")
    httpx_mock.add_response(method="POST", json={"ok": True}, status_code=200)
    exit_code = notify_drift.main([
        "--title", "x", "--severity", "warn", "--body", "b",
    ])
    assert exit_code == 0
