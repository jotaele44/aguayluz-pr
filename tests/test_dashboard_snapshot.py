from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gen_dashboard_snapshot import ENDPOINTS, OUT, generate_snapshot  # noqa: E402


@pytest.fixture(scope="module")
def snapshot() -> dict[str, object]:
    return generate_snapshot()


def test_snapshot_covers_every_declared_endpoint(snapshot: dict[str, object]) -> None:
    assert set(snapshot) == {endpoint.split("?", 1)[0] for endpoint in ENDPOINTS}
    assert isinstance(snapshot["/health"], dict)
    assert snapshot["/health"]["status"] == "ok"
    assert snapshot["/assets"]
    assert isinstance(snapshot["/municipios.geojson"], dict)
    assert snapshot["/municipios.geojson"]["type"] == "FeatureCollection"


def test_committed_snapshot_matches_generator(snapshot: dict[str, object]) -> None:
    assert json.loads(OUT.read_text(encoding="utf-8")) == snapshot
