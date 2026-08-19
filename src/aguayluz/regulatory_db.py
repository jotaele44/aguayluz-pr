"""Loaders, checkpoint store, and SQLite builder for the regulatory ingestion framework.

Mirrors :mod:`aguayluz.alert_db`: JSONL is the source of truth for observations,
receipts, and entity links; SQLite (``schemas/sql/regulatory_system.sql``) is a
derived, queryable projection built on demand. Checkpoints are small per-provider
JSON files — resumable discovery state only, never queried, so they stay out of
SQLite.

This module is pure persistence plumbing: no network I/O, no scheduler, no entity
promotion. It gives ``research/regulatory/contracts.py``'s design-only
``RegulatoryProviderAdapter`` protocol somewhere real to write its output, once a
live adapter is built on top of it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import DATA_DIR, SCHEMAS_DIR
from .models import validate_against_schema

DDL_PATH = SCHEMAS_DIR / "sql" / "regulatory_system.sql"
OBSERVATIONS_PATH = DATA_DIR / "regulatory_observations.jsonl"
RECEIPTS_PATH = DATA_DIR / "regulatory_source_receipts.jsonl"
LINKS_PATH = DATA_DIR / "regulatory_entity_links.jsonl"
CHECKPOINTS_DIR = DATA_DIR / "regulatory_checkpoints"

#: Matches contracts.py's Provider StrEnum and every schema's closed provider enum.
PROVIDERS = frozenset({"EPA", "FDA", "USGS", "DRNA", "PRASA_AAA", "PREQB"})

_OBSERVATION_COLUMNS = (
    "observation_id", "record_family", "provider", "provider_record_id",
    "provider_parent_record_id", "observed_at", "valid_from", "valid_until",
    "retrieved_at", "source_receipt_id", "normalization_version", "evidence_tier",
    "freshness_state", "supersedes_observation_id", "source_asserted_status",
    "identifiers", "payload",
)
_OBSERVATION_JSON_FIELDS = ("identifiers", "payload")
_RECEIPT_COLUMNS = (
    "receipt_id", "provider", "retrieved_at", "request_locator", "http_status",
    "sha256", "byte_count", "media_type", "etag", "last_modified",
    "retrieval_status", "checkpoint_id", "redactions", "error_class", "error_message",
)
_RECEIPT_JSON_FIELDS = ("redactions",)
_LINK_COLUMNS = (
    "candidate_id", "observation_id", "candidate_asset_id", "decision_state",
    "match_strength", "score", "match_features", "contradictions", "created_at",
    "decided_at", "decided_by", "decision_rationale", "supersedes_candidate_id",
)
_LINK_JSON_FIELDS = ("match_features", "contradictions")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )


def load_regulatory_observations(path: Path = OBSERVATIONS_PATH) -> list[dict[str, Any]]:
    rows = _read_jsonl(path)
    for r in rows:
        validate_against_schema("regulatory_observation", r)
    return rows


def load_regulatory_receipts(path: Path = RECEIPTS_PATH) -> list[dict[str, Any]]:
    rows = _read_jsonl(path)
    for r in rows:
        validate_against_schema("regulatory_source_receipt", r)
    return rows


def load_regulatory_links(path: Path = LINKS_PATH) -> list[dict[str, Any]]:
    rows = _read_jsonl(path)
    for r in rows:
        validate_against_schema("regulatory_entity_link", r)
    return rows


def merge_observations(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge by ``observation_id``; a re-normalized row replaces its prior version."""
    by_id = {r["observation_id"]: r for r in existing}
    for r in new:
        by_id[r["observation_id"]] = r
    return sorted(by_id.values(), key=lambda r: (r["provider"], r["observation_id"]))


def merge_receipts(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge by ``receipt_id``; receipts are otherwise immutable once written."""
    by_id = {r["receipt_id"]: r for r in existing}
    for r in new:
        by_id[r["receipt_id"]] = r
    return sorted(by_id.values(), key=lambda r: (r["provider"], r["receipt_id"]))


def merge_links(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge by ``candidate_id``; a later decision (e.g. proposed -> approved) replaces
    the prior row for the same candidate rather than accumulating duplicates."""
    by_id = {r["candidate_id"]: r for r in existing}
    for r in new:
        by_id[r["candidate_id"]] = r
    return sorted(by_id.values(), key=lambda r: r["candidate_id"])


def write_regulatory_observations(rows: list[dict], path: Path = OBSERVATIONS_PATH) -> None:
    """Validate ``rows`` against the schema, then merge and persist.

    Existing on-disk rows are re-validated too (via :func:`load_regulatory_observations`)
    rather than read raw, so a hand-edited or otherwise corrupted file is caught here
    instead of silently propagating into the merge.
    """
    for r in rows:
        validate_against_schema("regulatory_observation", r)
    _write_jsonl(path, merge_observations(load_regulatory_observations(path), rows))


def write_regulatory_receipts(rows: list[dict], path: Path = RECEIPTS_PATH) -> None:
    for r in rows:
        validate_against_schema("regulatory_source_receipt", r)
    _write_jsonl(path, merge_receipts(load_regulatory_receipts(path), rows))


def write_regulatory_links(rows: list[dict], path: Path = LINKS_PATH) -> None:
    for r in rows:
        validate_against_schema("regulatory_entity_link", r)
    _write_jsonl(path, merge_links(load_regulatory_links(path), rows))


def _checkpoint_path(provider: str, root: Path) -> Path:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown regulatory provider: {provider!r}")
    return root / f"{provider}.json"


def load_checkpoint(provider: str, root: Path = CHECKPOINTS_DIR) -> dict[str, Any] | None:
    """Resumable discovery state for one provider, or ``None`` if never checkpointed."""
    path = _checkpoint_path(provider, root)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"checkpoint for {provider!r} is not a JSON object: {path}")
    return data


def save_checkpoint(provider: str, checkpoint: dict[str, Any], root: Path = CHECKPOINTS_DIR) -> None:
    """Persist one provider's resumable discovery state.

    No secrets belong here — ``contracts.py``'s ``DiscoveryCheckpoint`` documents this
    as opaque cursor/watermark state only, the same boundary the source receipts and
    the design doc's runtime activation gates require.
    """
    path = _checkpoint_path(provider, root)
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _observation_row(o: dict[str, Any]) -> tuple:
    return tuple(
        json.dumps(o.get(c), ensure_ascii=False) if c in _OBSERVATION_JSON_FIELDS else o.get(c)
        for c in _OBSERVATION_COLUMNS
    )


def _receipt_row(r: dict[str, Any]) -> tuple:
    return tuple(
        json.dumps(r.get(c, []), ensure_ascii=False) if c in _RECEIPT_JSON_FIELDS else r.get(c)
        for c in _RECEIPT_COLUMNS
    )


def _link_row(link: dict[str, Any]) -> tuple:
    return tuple(
        json.dumps(link.get(c, []), ensure_ascii=False) if c in _LINK_JSON_FIELDS else link.get(c)
        for c in _LINK_COLUMNS
    )


def _insert(conn: sqlite3.Connection, table: str, columns: tuple[str, ...], row: tuple) -> None:
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", row
    )


def build_sqlite(
    db_path: str | Path = ":memory:",
    *,
    observations: list[dict] | None = None,
    receipts: list[dict] | None = None,
    links: list[dict] | None = None,
) -> sqlite3.Connection:
    """Create the regulatory SQLite DB from the DDL and load the given (or on-disk) rows.

    Returns the open connection (caller closes). Pass a file path to persist; defaults
    to an in-memory DB for tests/CLI dry runs. Mirrors
    :func:`aguayluz.alert_db.build_sqlite`.
    """
    observations = load_regulatory_observations() if observations is None else observations
    receipts = load_regulatory_receipts() if receipts is None else receipts
    links = load_regulatory_links() if links is None else links

    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL_PATH.read_text(encoding="utf-8"))

    # Receipts first: observations reference them by foreign key.
    for r in receipts:
        _insert(conn, "regulatory_source_receipts", _RECEIPT_COLUMNS, _receipt_row(r))
    for o in observations:
        _insert(conn, "regulatory_observations", _OBSERVATION_COLUMNS, _observation_row(o))
    for link in links:
        _insert(conn, "regulatory_entity_links", _LINK_COLUMNS, _link_row(link))
    conn.commit()
    return conn
