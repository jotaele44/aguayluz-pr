"""Read-only evidence readiness API for the hydro acquisition plane.

The endpoint never reports source existence as acquired bytes or qualified MWh.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/hydro-intelligence", tags=["hydro-intelligence"])
REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "config" / "hydro_intelligence_sources.v1.json"


def raw_root() -> Path:
    workspace = os.getenv("AGUAYLUZ_DATA_HOME", "").strip()
    data = Path(workspace) / "data" if workspace else REPO_ROOT / "data"
    return data / "hydro_intelligence" / "raw"


def source_artifact_state(root: Path, source_id: str) -> dict[str, Any]:
    source_dir = root / source_id
    if not source_dir.is_dir():
        return {"acquisition_state": "NOT_ACQUIRED", "byte_sha256": None,
                "last_success_utc": None}
    receipts = sorted(source_dir.glob("*/*.receipt.json"))
    if not receipts:
        return {"acquisition_state": "NOT_ACQUIRED", "byte_sha256": None,
                "last_success_utc": None}
    validated = []
    for receipt_path in receipts:
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            digest = receipt["sha256"]
            if (receipt_path.is_symlink() or receipt_path.parent.is_symlink() or
                    receipt_path.parent.parent.is_symlink()):
                raise ValueError("Symlinked evidence path")
            if (receipt.get("source_id") != source_id or
                    len(digest) != 64 or any(x not in "0123456789abcdef" for x in digest)):
                raise ValueError("Receipt identity mismatch")
            artifact_path = receipt_path.with_name(digest)
            if (not artifact_path.is_file() or artifact_path.is_symlink() or
                    receipt_path.name != digest + ".receipt.json" or
                    artifact_path.parent.name != digest[:2] or
                    not isinstance(receipt.get("fetched_at"), str)):
                raise ValueError("Missing original bytes")
            hasher = hashlib.sha256()
            with artifact_path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(block)
            if hasher.hexdigest() != digest or artifact_path.stat().st_size != receipt["byte_count"]:
                raise ValueError("Source bytes corrupted")
            validated.append(receipt)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return {"acquisition_state": "HASH_MISMATCH_OR_INVALID_RECEIPT",
                    "byte_sha256": None, "last_success_utc": None}
    latest = max(validated, key=lambda item: (item["fetched_at"], item["sha256"]))
    return {"acquisition_state": "RAW_FROZEN_NOT_PARSED",
            "byte_sha256": latest["sha256"],
            "last_success_utc": latest["fetched_at"]}



def source_readiness(registry: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    sources = []
    for source in registry["source_families"]:
        evidence = source_artifact_state(root, source["source_id"]) if root is not None else {"acquisition_state": "NOT_ACQUIRED", "byte_sha256": None, "last_success_utc": None}
        sources.append({
            "source_id": source["source_id"],
            "authority": source["authority"],
            "index_url": source["index_url"],
            "artifact_type": source["artifact_type"],
            "cadence_hours": source["discovery_interval_hours"],
            **evidence,
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
    return source_readiness(registry, raw_root())
