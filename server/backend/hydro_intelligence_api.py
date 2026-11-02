"""Read-only evidence readiness API for the hydro acquisition plane.

The endpoint never reports source existence as acquired bytes or qualified MWh.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/hydro-intelligence", tags=["hydro-intelligence"])
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "hydro_intelligence_sources.v1.json"


def source_readiness(registry: dict[str, Any]) -> dict[str, Any]:
    sources = []
    for source in registry["source_families"]:
        sources.append({
            "source_id": source["source_id"],
            "authority": source["authority"],
            "index_url": source["index_url"],
            "artifact_type": source["artifact_type"],
            "cadence_hours": source["discovery_interval_hours"],
            "acquisition_state": "NOT_VERIFIED",
            "byte_sha256": None,
            "last_success_utc": None,
            "parser_state": "NOT_VERIFIED",
            "certification": "WITHHELD",
        })
    return {
        "schema_version": "aguayluz.hydro-intelligence.readiness/v1",
        "sources": sources,
        "source_count": len(sources),
        "source_registry_state": "CONFIGURED_NOT_RUNNING",
        "operational_ingestion": False,
        "canonical_promotion": False,
        "certification": "WITHHELD",
        "known_limits": "Registry presence is not evidence of download, parsing or certified generation.",
    }


@router.get("/sources")
def hydro_sources() -> dict[str, Any]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return source_readiness(registry)
