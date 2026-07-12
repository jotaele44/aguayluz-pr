from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mycelial_observation_common import (  # noqa: E402
    aggregate_rows,
    dedupe_rows,
    normalize_rows,
    observations_geojson,
    verify_rows,
)


def _observation(idx: int = 1, **overrides):
    row = {
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
        "lat": 18.1631 + idx / 100000,
        "lon": -66.7221,
        "coordinate_precision_m": 5,
        "location_source": "gps",
        "photo_refs": [],
        "voucher_ref": None,
        "observer_type": "researcher",
        "source_ref": f"local://example/{idx}",
        "source_hash": None,
        "evidence_tier": "T2",
        "license_id": "license_abcdef123456",
        "access_guidance_present": False,
        "review_status": "accepted",
        "confidence": 80,
    }
    row.update(overrides)
    return row


def test_normalize_verify_aggregate_export_shape() -> None:
    rows = normalize_rows([_observation(1), _observation(2)])
    assert len(rows) == 2
    assert rows[0]["lat"] == 18.16311

    rows, clusters = dedupe_rows(rows)
    verified, statuses = verify_rows(rows, clusters)
    aggregates = aggregate_rows(verified)
    geojson = observations_geojson(verified)

    assert len(statuses) == 2
    assert aggregates
    assert geojson["type"] == "FeatureCollection"
    assert geojson["features"][0]["geometry"]["type"] == "Point"


def test_rejected_rows_do_not_export_to_geojson() -> None:
    rows = normalize_rows([_observation(review_status="rejected")])
    geojson = observations_geojson(rows)
    assert geojson["features"] == []
