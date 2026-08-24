from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gen_dashboard_snapshot import ENDPOINTS, OUT, generate_snapshot  # noqa: E402


@pytest.fixture(scope="module")
def snapshot() -> dict[str, object]:
    return generate_snapshot()


def _stable_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _stable_payload(v) for k, v in value.items() if k != "modified_at"}
    if isinstance(value, list):
        return [_stable_payload(item) for item in value]
    return value


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_snapshot_covers_every_declared_endpoint(snapshot: dict[str, object]) -> None:
    assert set(snapshot) == {endpoint.split("?", 1)[0] for endpoint in ENDPOINTS}
    assert isinstance(snapshot["/health"], dict)
    assert snapshot["/health"]["status"] == "ok"
    assert snapshot["/assets"]
    assert isinstance(snapshot["/municipios.geojson"], dict)
    assert snapshot["/municipios.geojson"]["type"] == "FeatureCollection"


def test_committed_snapshot_matches_generator(snapshot: dict[str, object]) -> None:
    expected = _stable_payload(json.loads(OUT.read_text(encoding="utf-8")))
    actual = _stable_payload(snapshot)
    if expected == actual:
        return

    assert isinstance(expected, dict)
    assert isinstance(actual, dict)
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatched = sorted(k for k in set(expected) & set(actual) if expected[k] != actual[k])
    detail = "; ".join(
        [
            f"missing={missing[:5]}",
            f"extra={extra[:5]}",
            f"mismatched={mismatched[:5]}",
            f"expected_sha256={_digest(expected)}",
            f"actual_sha256={_digest(actual)}",
        ]
    )
    pytest.fail(f"dashboard snapshot drift after modified_at normalization: {detail}")
