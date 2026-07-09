from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mycelial_observation_common import observations_geojson  # noqa: E402


def _observation() -> dict[str, object]:
    return {
        "source_id": "obs_src_abcdef123456",
        "observed_at": "2026-07-07T00:00:00Z",
        "reported_at": "2026-07-07T01:00:00Z",
        "taxon_label_raw": "Fungi",
        "taxon_rank": "kingdom",
        "scientific_name": None,
        "common_name": None,
        "substrate": "unknown",
        "habitat_context": "forest",
        "municipality": "Adjuntas",
        "lat": 18.16311,
        "lon": -66.7221,
        "coordinate_precision_m": 5,
        "location_source": "gps",
        "photo_refs": [],
        "voucher_ref": None,
        "observer_type": "researcher",
        "source_ref": "local://example/1",
        "source_hash": None,
        "evidence_tier": "T2",
        "license_id": "license_abcdef123456",
        "access_guidance_present": False,
        "review_status": "accepted",
        "confidence": 80,
    }


def test_mycelial_backend_endpoint_shapes(monkeypatch, tmp_path) -> None:
    from server.backend import main

    obs = _observation()
    grid = {"grid_id": "18.16_-66.72", "observation_count": 1, "accepted_count": 1}
    report = {"status": "ok", "license_gaps": ["license_abcdef123456"]}
    obs_geojson = observations_geojson([obs])
    grid_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-66.7221, 18.16311]},
                "properties": grid,
            }
        ],
    }

    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    (outputs_dir / "mycelial_observation_report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )

    monkeypatch.setattr(main, "_mycelial_observations", [obs])
    monkeypatch.setattr(main, "_mycelial_grid", [grid])
    monkeypatch.setattr(main, "_mycelial_geojson", obs_geojson)
    monkeypatch.setattr(main, "_mycelial_grid_geojson", grid_geojson)
    monkeypatch.setattr(main, "OUTPUTS", outputs_dir)

    health_payload = json.loads(main.health().body)
    assert health_payload["counts"]["mycelial_observations"] == 1
    assert health_payload["counts"]["mycelial_grid_cells"] == 1

    observations_payload = json.loads(main.mycelial_observations(municipio="Adjuntas").body)
    assert observations_payload[0]["municipality"] == "Adjuntas"
    assert json.loads(main.mycelial_observations_geojson().body)["features"][0]["geometry"]["type"] == "Point"
    assert json.loads(main.mycelial_grid_geojson().body)["features"][0]["properties"]["grid_id"]
    assert json.loads(main.mycelial_summary().body)["license_gaps"] == ["license_abcdef123456"]
