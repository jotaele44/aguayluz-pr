from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gen_dashboard_snapshot import ENDPOINTS, OUT, generate_snapshot  # noqa: E402


def test_snapshot_covers_every_declared_endpoint() -> None:
    snapshot = generate_snapshot()

    assert set(snapshot) == {endpoint.split("?", 1)[0] for endpoint in ENDPOINTS}
    assert snapshot["/health"]["status"] == "ok"
    assert snapshot["/assets"]
    assert snapshot["/municipios.geojson"]["type"] == "FeatureCollection"


def test_committed_snapshot_matches_generator() -> None:
    assert json.loads(OUT.read_text(encoding="utf-8")) == generate_snapshot()
