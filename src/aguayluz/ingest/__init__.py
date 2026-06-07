"""Public-data ingestion adapters.

Each adapter (`frs`, `hifld`, ...) parses a source-specific format into a
common `FacilitySeed` shape. `pipeline.ingest_seeds()` then snaps each seed
through WATERS and produces validated `UtilityAsset` records.

This package is deliberately data-source-agnostic: the same pipeline serves
EPA FRS, HIFLD, FEMA, or any future adapter as long as it emits FacilitySeed.
"""

from .pipeline import (
    EventIngestResult,
    FacilitySeed,
    IngestResult,
    ingest_event_seeds,
    ingest_seeds,
)

__all__ = [
    "FacilitySeed",
    "IngestResult",
    "ingest_seeds",
    "EventIngestResult",
    "ingest_event_seeds",
]
