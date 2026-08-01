"""Generated-style dependency-free client for Agua y Luz shadow incident operations."""
from __future__ import annotations

import json
import urllib.request
from typing import Any


class WaterIncidentClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, key: str | None = None) -> Any:
        headers = {"Accept": "application/json", "X-Shadow-Mode": "true"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        if key:
            headers["Idempotency-Key"] = key
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def intake(self, envelope: dict[str, Any], key: str) -> Any:
        return self._request("POST", "/water-disruption/intake", envelope, key)

    def validation_queue(self) -> Any:
        return self._request("GET", "/water-disruption/validation-queue")

    def incidents(self) -> Any:
        return self._request("GET", "/water-disruption/incidents")
