"""Committed JSONL store for the NWS hydromet plane.

Stdlib + pydantic only: the backend imports this module, and the gui-parity CI job
installs nothing heavier than fastapi/uvicorn/jsonschema.

Write discipline (``apply_source_run``):

* records, relationships and manifestations are append-only and de-duplicated by id —
  an existing row is never rewritten;
* a source may prune only whole canonical events under its own prefix (retention), so a
  revision chain is either kept intact or dropped intact and no ``supersedes`` pointer
  dangles;
* manifestations are pruned to the closure referenced by the remaining records,
  relationships and the per-source receipts, so a fresh checkout integrity-checks PASS;
* the post-write state must pass :func:`aguayluz.hazard_plane.integrity_report` or
  nothing is written (fail closed).
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .. import CONFIG_DIR, DATA_DIR
from ..hazard_plane import (
    HazardRecord,
    HazardRelationship,
    Manifestation,
    current_records,
    integrity_report,
)
from . import SOURCE_PREFIXES

SOURCES_CONFIG = CONFIG_DIR / "hydromet_sources.v1.json"
RECEIPTS_SCHEMA = "aguayluz.hydromet-receipts/v1"


@dataclass(frozen=True)
class HydrometPaths:
    """Locations of every hydromet file under one data directory."""

    data_dir: Path

    @property
    def records(self) -> Path:
        return self.data_dir / "hydromet_records.jsonl"

    @property
    def relationships(self) -> Path:
        return self.data_dir / "hydromet_relationships.jsonl"

    @property
    def manifestations(self) -> Path:
        return self.data_dir / "hydromet_manifestations.jsonl"

    @property
    def receipts(self) -> Path:
        return self.data_dir / "hydromet_receipts.json"

    @property
    def gauge_state(self) -> Path:
        return self.data_dir / "nwps_gauge_state.jsonl"

    @property
    def accounting(self) -> Path:
        return self.data_dir / "hydromet_source_accounting.jsonl"

    def snapshot_dir(self, source_id: str) -> Path:
        return self.data_dir / "hydromet_snapshots" / source_id


def hydromet_paths(data_dir: Path | str | None = None) -> HydrometPaths:
    return HydrometPaths(Path(data_dir) if data_dir is not None else DATA_DIR)


# --------------------------------------------------------------------------- io


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"non-object JSONL row in {path}")
        rows.append(row)
    return rows


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        # mkstemp creates the file owner-only. Replacing a file keeps that file's own
        # mode; a new file stays owner-only rather than being widened here.
        if path.exists():
            os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    _atomic_write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    _atomic_write(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def _dump(model: Any) -> dict[str, Any]:
    # Every optional plane field defaults to None, so dropping nulls round-trips and keeps
    # the committed files (30 days of per-municipio rainfall) about a third smaller.
    return model.model_dump(mode="json", exclude_none=True)


# --------------------------------------------------------------------- registry


def load_source_registry(path: Path | None = None) -> dict[str, Any]:
    """``config/hydromet_sources.v1.json`` — the single source of URLs and cadences."""
    payload = read_json(path or SOURCES_CONFIG, default=None)
    if not isinstance(payload, dict):
        return {"sources": [], "unresolved_material": ["SOURCE_CONFIG_MISSING_OR_INVALID"]}
    return payload


def registry_source(source_id: str, registry: dict[str, Any] | None = None) -> dict[str, Any] | None:
    for source in (registry or load_source_registry()).get("sources", []):
        if source.get("source_id") == source_id:
            return source
    return None


# ------------------------------------------------------------------------ loads


def load_records(data_dir: Path | str | None = None) -> list[HazardRecord]:
    return [HazardRecord.model_validate(r) for r in read_jsonl(hydromet_paths(data_dir).records)]


def load_relationships(data_dir: Path | str | None = None) -> list[HazardRelationship]:
    rows = read_jsonl(hydromet_paths(data_dir).relationships)
    return [HazardRelationship.model_validate(r) for r in rows]


def load_manifestations(data_dir: Path | str | None = None) -> list[Manifestation]:
    rows = read_jsonl(hydromet_paths(data_dir).manifestations)
    return [Manifestation.model_validate(r) for r in rows]


def load_receipts(data_dir: Path | str | None = None) -> dict[str, Any]:
    payload = read_json(hydromet_paths(data_dir).receipts, default=None)
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), dict):
        return {"schema_version": RECEIPTS_SCHEMA, "sources": {}}
    return payload


def load_gauge_state(data_dir: Path | str | None = None) -> list[dict[str, Any]]:
    return read_jsonl(hydromet_paths(data_dir).gauge_state)


def current_by_event(records: Iterable[HazardRecord], prefix: str) -> dict[str, HazardRecord]:
    """Current (non-superseded) revision per canonical event under ``prefix``."""
    owned = [r for r in records if r.canonical_event_id.startswith(prefix)]
    return {r.canonical_event_id: r for r in current_records(owned)}


def revision_chains(records: Iterable[HazardRecord], prefix: str) -> dict[str, list[HazardRecord]]:
    """Revisions per canonical event under ``prefix``, oldest first (follows supersedes)."""
    by_event: dict[str, list[HazardRecord]] = {}
    for record in records:
        if record.canonical_event_id.startswith(prefix):
            by_event.setdefault(record.canonical_event_id, []).append(record)
    chains: dict[str, list[HazardRecord]] = {}
    for event_id, rows in by_event.items():
        by_supersedes = {r.supersedes_record_id: r for r in rows if r.supersedes_record_id}
        heads = [r for r in rows if not r.supersedes_record_id]
        chain: list[HazardRecord] = []
        node = heads[0] if heads else None
        seen: set[str] = set()
        while node is not None and node.record_id not in seen:
            chain.append(node)
            seen.add(node.record_id)
            node = by_supersedes.get(node.record_id)
        # Rows that are not reachable from the head (should not happen) are kept at the
        # end in file order rather than silently dropped.
        chain.extend(r for r in rows if r.record_id not in seen)
        chains[event_id] = chain
    return chains


# ------------------------------------------------------------------- provenance


def manifestation_id(source_id: str, byte_sha256: str) -> str:
    return f"HYDROMET:{source_id}:{byte_sha256[:32]}"


def relationship_id(subject_id: str, predicate: str, object_id: str) -> str:
    digest = sha256(f"{subject_id}|{predicate}|{object_id}".encode()).hexdigest()
    return f"HYDROMET_REL:{digest[:32]}"


def freeze_bytes(
    source_id: str,
    payload: bytes,
    *,
    source_authority: str,
    source_system: str,
    source_record_id: str,
    source_url: str,
    retrieved_at: datetime,
    retrieval_query: str | None = None,
    record_count: int | None = None,
    schema_signature: str | None = None,
    headers: dict[str, str] | None = None,
    snapshot_dir: Path | None = None,
    extension: str = "bin",
) -> Manifestation:
    """Hash the exact response bytes and (optionally) keep them on disk.

    Called before any parsing so the manifestation describes what the source sent,
    not what the normalizer understood.
    """
    digest = sha256(payload).hexdigest()
    if snapshot_dir is not None:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        target = snapshot_dir / f"{digest}.{extension}"
        if not target.exists():
            target.write_bytes(payload)
    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    return Manifestation(
        manifestation_id=manifestation_id(source_id, digest),
        source_authority=source_authority,
        source_system=source_system,
        source_record_id=source_record_id,
        source_url=source_url,
        retrieval_query=retrieval_query,
        retrieved_at_utc=retrieved_at.astimezone(timezone.utc),
        byte_sha256=digest,
        schema_signature=schema_signature,
        record_count=record_count,
        http_etag=lowered.get("etag"),
        http_last_modified=lowered.get("last-modified"),
    )


# ------------------------------------------------------------------------ write


@dataclass
class SourceRun:
    """Everything one ingest run wants to add for one source."""

    source_id: str
    manifestations: list[Manifestation] = field(default_factory=list)
    records: list[HazardRecord] = field(default_factory=list)
    relationships: list[HazardRelationship] = field(default_factory=list)
    #: Called with the current revision of each canonical event the source owns; a
    #: False result drops the whole event (all revisions + their relationships).
    retain_event: Callable[[HazardRecord], bool] | None = None


def _referenced_manifestations(
    records: Iterable[HazardRecord],
    relationships: Iterable[HazardRelationship],
    receipts: dict[str, Any],
) -> set[str]:
    referenced = {r.manifestation_id for r in records}
    for rel in relationships:
        referenced.update(rel.source_manifestation_ids)
    for receipt in receipts.get("sources", {}).values():
        referenced.update(receipt.get("referenced_manifestation_ids") or [])
    return referenced


def apply_source_run(
    run: SourceRun,
    data_dir: Path | str | None = None,
    *,
    referenced_manifestation_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Merge one run into the committed files; returns what changed.

    ``referenced_manifestation_ids`` are the ids the source's state file points at; they
    are recorded in the source receipt by :func:`record_receipt`, and passed here too so
    the closure computed before the receipt is written already keeps them.
    """
    paths = hydromet_paths(data_dir)
    prefix = SOURCE_PREFIXES.get(run.source_id)
    if prefix is None:
        raise ValueError(f"unknown hydromet source {run.source_id!r}")
    for record in run.records:
        if not record.canonical_event_id.startswith(prefix):
            raise ValueError(
                f"{run.source_id} may only write {prefix}* events, got {record.canonical_event_id}"
            )

    records = load_records(paths.data_dir)
    relationships = load_relationships(paths.data_dir)
    manifestations = load_manifestations(paths.data_dir)
    receipts = load_receipts(paths.data_dir)

    record_ids = {r.record_id for r in records}
    added_records = [r for r in run.records if r.record_id not in record_ids]
    records.extend(added_records)
    rel_ids = {r.relationship_id for r in relationships}
    added_relationships = []
    for rel in run.relationships:
        if rel.relationship_id not in rel_ids:
            added_relationships.append(rel)
            rel_ids.add(rel.relationship_id)
    relationships.extend(added_relationships)
    man_ids = {m.manifestation_id for m in manifestations}
    added_manifestations = []
    for man in run.manifestations:
        if man.manifestation_id not in man_ids:
            added_manifestations.append(man)
            man_ids.add(man.manifestation_id)
    manifestations.extend(added_manifestations)

    pruned_events: list[str] = []
    if run.retain_event is not None:
        for event_id, current in current_by_event(records, prefix).items():
            if not run.retain_event(current):
                pruned_events.append(event_id)
    if pruned_events:
        dropped = set(pruned_events)
        dropped_ids = {r.record_id for r in records if r.canonical_event_id in dropped}
        records = [r for r in records if r.record_id not in dropped_ids]
        relationships = [
            rel for rel in relationships
            if rel.subject_id not in dropped_ids and rel.object_id not in dropped_ids
        ]

    referenced = _referenced_manifestations(records, relationships, receipts)
    if referenced_manifestation_ids:
        referenced.update(referenced_manifestation_ids)
    kept_manifestations = [m for m in manifestations if m.manifestation_id in referenced]

    report = integrity_report(records, relationships, kept_manifestations)
    if report["state"] != "PASS":
        raise ValueError(f"hydromet integrity would fail: {report['unresolved']}")

    write_jsonl(paths.records, (_dump(r) for r in records))
    write_jsonl(paths.relationships, (_dump(r) for r in relationships))
    write_jsonl(paths.manifestations, (_dump(m) for m in kept_manifestations))
    return {
        "records_added": len(added_records),
        "relationships_added": len(added_relationships),
        "manifestations_added": len(added_manifestations),
        "manifestations_pruned": len(manifestations) - len(kept_manifestations),
        "events_pruned": len(pruned_events),
        "integrity": report["state"],
    }


def record_receipt(
    source_id: str,
    *,
    status: str,
    attempted_at: datetime,
    data_dir: Path | str | None = None,
    error: str | None = None,
    summary: dict[str, Any] | None = None,
    referenced_manifestation_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Write the latest attempt for ``source_id``; a failure keeps the last success."""
    if status not in {"PASS", "FAIL"}:
        raise ValueError("receipt status must be PASS or FAIL")
    paths = hydromet_paths(data_dir)
    receipts = load_receipts(paths.data_dir)
    previous = receipts["sources"].get(source_id, {})
    attempted = attempted_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    entry: dict[str, Any] = {
        "source_id": source_id,
        "last_attempt_utc": attempted,
        "last_status": status,
        "last_error": error if status == "FAIL" else None,
        "last_success_utc": previous.get("last_success_utc"),
        "last_success": previous.get("last_success"),
        "referenced_manifestation_ids": previous.get("referenced_manifestation_ids", []),
    }
    if status == "PASS":
        entry["last_success_utc"] = attempted
        entry["last_success"] = summary or {}
        entry["referenced_manifestation_ids"] = sorted(set(referenced_manifestation_ids or []))
    receipts["schema_version"] = RECEIPTS_SCHEMA
    receipts["sources"][source_id] = entry
    write_json(paths.receipts, receipts)
    return entry


def append_accounting(row: dict[str, Any], data_dir: Path | str | None = None) -> None:
    """Append one run's arithmetic to the (gitignored) accounting log."""
    path = hydromet_paths(data_dir).accounting
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


# ------------------------------------------------------------------------- read


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def freshness(receipt: dict[str, Any] | None, source: dict[str, Any], now: datetime) -> dict[str, Any]:
    """FRESH / STALE / FAILED / NEVER for one source, from its receipt and registry entry."""
    if not receipt:
        return {"state": "NEVER", "age_seconds": None, "max_age_seconds": source.get("max_age_seconds")}
    last_success = _parse_utc(receipt.get("last_success_utc"))
    age = (now - last_success).total_seconds() if last_success else None
    max_age = source.get("max_age_seconds")
    if receipt.get("last_status") == "FAIL":
        state = "FAILED"
    elif age is None:
        state = "NEVER"
    elif isinstance(max_age, (int, float)) and age > max_age:
        state = "STALE"
    else:
        state = "FRESH"
    return {"state": state, "age_seconds": age, "max_age_seconds": max_age}


def integrity(data_dir: Path | str | None = None) -> dict[str, Any]:
    """Hazard-plane integrity over the hydromet files, plus receipt references."""
    paths = hydromet_paths(data_dir)
    manifestations = load_manifestations(paths.data_dir)
    report = integrity_report(
        load_records(paths.data_dir), load_relationships(paths.data_dir), manifestations
    )
    known = {m.manifestation_id for m in manifestations}
    receipts = load_receipts(paths.data_dir)
    missing_state = sorted({
        mid
        for receipt in receipts.get("sources", {}).values()
        for mid in receipt.get("referenced_manifestation_ids") or []
        if mid not in known
    })
    report["missing_state_manifestations"] = missing_state
    if missing_state:
        report["unresolved"] = [*report["unresolved"], "MISSING_STATE_MANIFESTATIONS"]
        report["state"] = "FAIL"
    return report


__all__ = [
    "HydrometPaths",
    "SourceRun",
    "append_accounting",
    "apply_source_run",
    "current_by_event",
    "freeze_bytes",
    "freshness",
    "hydromet_paths",
    "integrity",
    "load_gauge_state",
    "load_manifestations",
    "load_receipts",
    "load_records",
    "load_relationships",
    "load_source_registry",
    "manifestation_id",
    "read_json",
    "read_jsonl",
    "record_receipt",
    "registry_source",
    "relationship_id",
    "revision_chains",
    "write_json",
    "write_jsonl",
]
