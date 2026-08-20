#!/usr/bin/env python3
"""Generate the deterministic data snapshot embedded in offline dashboard exports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.backend.main import app  # noqa: E402

OUT = ROOT / "dashboard" / "src" / "lib" / "snapshot.json"
ENDPOINTS = (
    "/health",
    "/assets",
    "/assets.geojson",
    "/municipios.geojson",
    "/events?limit=500",
    "/readings",
    "/review-queue?limit=500",
    "/summary",
    "/summary/sectors",
    "/summary/coverage",
    "/system/status",
    "/alerts?limit=500",
    "/alerts/facets",
    "/alerts.geojson",
    "/alerts/dependencies",
    "/alerts/gaps",
)


def generate_snapshot() -> dict[str, object]:
    snapshot: dict[str, object] = {}
    with TestClient(app) as client:
        for endpoint in ENDPOINTS:
            response = client.get(endpoint)
            response.raise_for_status()
            snapshot[endpoint.split("?", 1)[0]] = response.json()
    return snapshot


def main() -> None:
    snapshot = generate_snapshot()
    OUT.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(ROOT)} ({len(snapshot)} endpoints)")


if __name__ == "__main__":
    main()
