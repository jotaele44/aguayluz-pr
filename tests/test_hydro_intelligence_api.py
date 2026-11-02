"""Hydroelectric readiness API contract: a registry is not acquired data."""
from server.backend.hydro_intelligence_api import source_readiness


def test_readiness_does_not_promote_unacquired_sources():
    registry = {
        "source_families": [
            {"source_id": "eia_923", "authority": "US EIA",
             "index_url": "https://www.eia.gov/electricity/data/eia923/",
             "artifact_type": "zip", "discovery_interval_hours": 24}
        ]
    }
    state = source_readiness(registry)
    assert state["source_count"] == 1
    assert state["certification"] == "WITHHELD"
    assert not state["operational_ingestion"]
    assert not state["canonical_promotion"]
    assert state["sources"][0]["byte_sha256"] is None
    assert state["sources"][0]["acquisition_state"] == "NOT_VERIFIED"
