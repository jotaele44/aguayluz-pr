"""Hydroelectric readiness API contract: a registry is not acquired data."""
from server.backend.hydro_intelligence_api import source_artifact_state, source_readiness


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
    assert state["sources"][0]["acquisition_state"] == "NOT_ACQUIRED"


def test_readiness_consumes_only_valid_frozen_receipts(tmp_path):
    from aguayluz.hydro_intelligence.acquisition import persist_bytes

    receipt = persist_bytes(tmp_path, "eia_923", "https://www.eia.gov/f923.zip",
                            b"frozen evidence")
    state = source_artifact_state(tmp_path, "eia_923")
    assert state["acquisition_state"] == "RAW_FROZEN_NOT_PARSED"
    assert state["byte_sha256"] == receipt.sha256

    artifact = tmp_path / "eia_923" / receipt.sha256[:2] / receipt.sha256
    artifact.write_bytes(b"corrupt evidence")
    broken = source_artifact_state(tmp_path, "eia_923")
    assert broken["acquisition_state"] == "HASH_MISMATCH_OR_INVALID_RECEIPT"
    assert broken["byte_sha256"] is None


def test_orphan_raw_bytes_never_misreported_as_not_acquired(tmp_path):
    source_dir = tmp_path / "eia_923" / "aa"
    source_dir.mkdir(parents=True)
    (source_dir / "unreceipted-source-bytes").write_bytes(b"orphan")
    state = source_artifact_state(tmp_path, "eia_923")
    assert state["acquisition_state"] == "UNRESOLVED_ORPHANED_EVIDENCE"
    assert state["byte_sha256"] is None


def test_empty_source_directory_is_not_acquired(tmp_path):
    (tmp_path / "eia_923").mkdir()
    state = source_artifact_state(tmp_path, "eia_923")
    assert state["acquisition_state"] == "NOT_ACQUIRED"
    assert state["byte_sha256"] is None
