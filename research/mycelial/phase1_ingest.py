"""Public import surface for the hardened Phase 1 research-ingest core."""
from .phase1_ingest_core import (
    ANALYTICS_STATUS,
    AUTHORIZATION_REF,
    CAPABILITY,
    SCHEMA_VERSION,
    SUPERSEDED_HOLD_REF,
    IngestReceipt,
    canonical_payload,
    ingest_jsonl_batch,
    initialize_database,
    raw_batch_bytes,
    training_candidate_only,
    validate_record,
)

__all__ = [
    "ANALYTICS_STATUS",
    "AUTHORIZATION_REF",
    "CAPABILITY",
    "SCHEMA_VERSION",
    "SUPERSEDED_HOLD_REF",
    "IngestReceipt",
    "canonical_payload",
    "ingest_jsonl_batch",
    "initialize_database",
    "raw_batch_bytes",
    "training_candidate_only",
    "validate_record",
]
