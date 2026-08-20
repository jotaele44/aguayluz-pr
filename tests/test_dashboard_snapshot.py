from __future__ import annotations

import json

from scripts.gen_dashboard_snapshot import ENDPOINTS, OUT, generate_snapshot


def test_snapshot_covers_every_declared_endpoint() -> None:
    snapshot = generate_snapshot()

    assert set(snapshot) == {endpoint.split("?", 1)[0] for endpoint in ENDPOINTS}
    assert snapshot["/health"]["status"] == "ok"
    assert snapshot["/assets"]
    assert snapshot["/municipios.geojson"]["type"] == "FeatureCollection"


def test_committed_snapshot_matches_generator() -> None:
    assert json.loads(OUT.read_text(encoding="utf-8")) == generate_snapshot()
