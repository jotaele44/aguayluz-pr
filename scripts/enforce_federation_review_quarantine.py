#!/usr/bin/env python3
"""Fail-closed review quarantine for AguaYLuz federation canonical streams.

Operator outputs remain complete evidence. Only source records whose review state
is accepted (or the legacy alias ``approved``) are allowed to contribute rows to
canonical federation streams. Non-accepted records remain in outputs/* and the
quarantine receipt, but cannot create canonical entities, relationships, alerts,
critical-notification eligibility, or topology/identity edges.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Keep direct execution and importlib-based tests on the same helper identity.
# When this module is loaded via spec_from_file_location, Python does not
# automatically add scripts/ to sys.path as it does for `python scripts/...`.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from prii_export_utils import fid as _fid  # noqa: E402

POLICY_VERSION = "federation-review-quarantine/1.0"
PRODUCER = "aguayluz-pr"
STREAM_ORDER = ("sources", "entities", "relationships", "alerts")
STREAM_SCHEMA = {
    "sources": "federation_source.schema.json",
    "entities": "federation_entity.schema.json",
    "relationships": "federation_relationship.schema.json",
    "alerts": "federation_alert.schema.json",
}
ACCEPTED = "accepted"
LEGACY_ACCEPTED = {"approved": ACCEPTED}
NON_ACCEPTED = {"needs_review", "rejected", "blocked"}
ALLOWED = {ACCEPTED, *NON_ACCEPTED, *LEGACY_ACCEPTED}


class QuarantineError(ValueError):
    """Raised when review state cannot be interpreted safely."""


def canonical_review_state(value: Any) -> tuple[str, str, bool]:
    raw = "" if value is None else str(value).strip()
    if raw in LEGACY_ACCEPTED:
        return raw, LEGACY_ACCEPTED[raw], True
    if raw in {ACCEPTED, *NON_ACCEPTED}:
        return raw, raw, False
    raise QuarantineError(f"missing/unknown review_status: {value!r}")


def _load_json(path: Path, *, required: bool = True) -> Any:
    if not path.is_file():
        if required:
            raise QuarantineError(f"missing required JSON file: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QuarantineError(f"cannot parse {path}: {exc}") from exc


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QuarantineError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise QuarantineError(f"{path}:{line_no}: row must be an object")
        rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_id(kind: str, row: dict[str, Any]) -> str:
    if kind == "asset":
        value = row.get("asset_id")
    elif kind == "event":
        value = row.get("event_id")
    else:
        value = row.get("alert_id")
    if not isinstance(value, str) or not value:
        raise QuarantineError(f"{kind} record missing stable id")
    return value


def _primary_entity_id(kind: str, record_id: str) -> str:
    if kind == "asset":
        return _fid("ent", "asset", record_id)
    if kind == "event":
        return _fid("ent", "event", record_id)
    raise AssertionError(kind)


def _review_index(kind: str, rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int]:
    accepted: dict[str, dict[str, Any]] = {}
    quarantined: list[dict[str, Any]] = []
    aliases = 0
    seen: set[str] = set()
    for row in rows:
        rid = _record_id(kind, row)
        if rid in seen:
            raise QuarantineError(f"duplicate {kind} stable id: {rid}")
        seen.add(rid)
        raw, state, alias = canonical_review_state(row.get("review_status"))
        aliases += int(alias)
        entry = {
            "kind": kind,
            "record_id": rid,
            "review_status_raw": raw,
            "review_status": state,
        }
        if state == ACCEPTED:
            accepted[rid] = entry
        else:
            entry["reason"] = f"review_status={state}"
            quarantined.append(entry)
    return accepted, quarantined, aliases


def enforce(outputs_dir: Path, federation_dir: Path) -> dict[str, Any]:
    assets = _load_json(outputs_dir / "utility_assets.json")
    events = _load_json(outputs_dir / "service_events.json")
    alerts = _load_json(outputs_dir / "alert_events.json", required=False)
    if alerts is None:
        alerts = []
    for label, rows in (("assets", assets), ("events", events), ("alerts", alerts)):
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise QuarantineError(f"{label} operator output must be an array of objects")

    accepted_assets, quarantined_assets, alias_assets = _review_index("asset", assets)
    accepted_events, quarantined_events, alias_events = _review_index("event", events)
    accepted_alerts, quarantined_alerts, alias_alerts = _review_index("alert", alerts)

    original = {stream: _load_jsonl(federation_dir / f"{stream}.jsonl") for stream in STREAM_ORDER}
    manifest_path = federation_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise QuarantineError("canonical manifest root must be an object")

    accepted_primary: set[str] = {
        _primary_entity_id("asset", rid) for rid in accepted_assets
    } | {
        _primary_entity_id("event", rid) for rid in accepted_events
    }
    quarantined_primary: set[str] = {
        _primary_entity_id("asset", item["record_id"]) for item in quarantined_assets
    } | {
        _primary_entity_id("event", item["record_id"]) for item in quarantined_events
    }

    entity_by_id: dict[str, dict[str, Any]] = {}
    for entity in original["entities"]:
        eid = entity.get("entity_id")
        if not isinstance(eid, str) or not eid:
            raise QuarantineError("canonical entity missing entity_id")
        if eid in entity_by_id:
            raise QuarantineError(f"duplicate canonical entity_id: {eid}")
        entity_by_id[eid] = dict(entity)

    for rid, review in accepted_assets.items():
        eid = _primary_entity_id("asset", rid)
        if eid not in entity_by_id:
            raise QuarantineError(f"accepted asset missing canonical entity: {rid}")
        attrs = entity_by_id[eid].get("attributes")
        attrs = dict(attrs) if isinstance(attrs, dict) else {}
        attrs.update({
            "review_status_raw": review["review_status_raw"],
            "review_status": ACCEPTED,
            "promotion_eligible": True,
        })
        entity_by_id[eid]["attributes"] = attrs

    for rid, review in accepted_events.items():
        eid = _primary_entity_id("event", rid)
        if eid not in entity_by_id:
            raise QuarantineError(f"accepted event missing canonical entity: {rid}")
        attrs = entity_by_id[eid].get("attributes")
        attrs = dict(attrs) if isinstance(attrs, dict) else {}
        attrs.update({
            "aguayluz_event_id": rid,
            "review_status_raw": review["review_status_raw"],
            "review_status": ACCEPTED,
            "promotion_eligible": True,
        })
        entity_by_id[eid]["attributes"] = attrs

    candidate_relationships: list[dict[str, Any]] = []
    referenced_support: set[str] = set()
    for relationship in original["relationships"]:
        left = relationship.get("source_entity_id")
        right = relationship.get("target_entity_id")
        if not isinstance(left, str) or not isinstance(right, str):
            raise QuarantineError("canonical relationship missing endpoint id")
        if left in quarantined_primary or right in quarantined_primary:
            continue
        if left not in entity_by_id or right not in entity_by_id:
            raise QuarantineError("canonical relationship references missing entity")
        if left not in accepted_primary and right not in accepted_primary:
            continue
        candidate_relationships.append(dict(relationship))
        if left not in accepted_primary:
            referenced_support.add(left)
        if right not in accepted_primary:
            referenced_support.add(right)

    kept_entity_ids = accepted_primary | referenced_support
    kept_entities = [
        entity_by_id[eid]
        for eid in entity_by_id
        if eid in kept_entity_ids
    ]

    kept_alerts: list[dict[str, Any]] = []
    accepted_alert_ids = {_fid("alrt", rid): review for rid, review in accepted_alerts.items()}
    for alert in original["alerts"]:
        aid = alert.get("alert_id")
        if not isinstance(aid, str) or not aid:
            raise QuarantineError("canonical alert missing alert_id")
        review = accepted_alert_ids.get(aid)
        if review is None:
            continue
        row = dict(alert)
        attrs = row.get("attributes")
        attrs = dict(attrs) if isinstance(attrs, dict) else {}
        attrs.update({
            "review_status_raw": review["review_status_raw"],
            "review_status": ACCEPTED,
            "promotion_eligible": True,
        })
        row["attributes"] = attrs
        entity_id = row.get("entity_id")
        if entity_id is not None and entity_id not in kept_entity_ids:
            raise QuarantineError(
                f"accepted alert {aid} references non-retained entity {entity_id}"
            )
        kept_alerts.append(row)

    referenced_sources: set[str] = set()
    for row in kept_entities:
        if isinstance(row.get("source_id"), str):
            referenced_sources.add(row["source_id"])
    for row in candidate_relationships:
        for key in ("source_id", "evidence_source_id"):
            if isinstance(row.get(key), str):
                referenced_sources.add(row[key])
    for row in kept_alerts:
        if isinstance(row.get("source_id"), str):
            referenced_sources.add(row["source_id"])

    kept_sources = [
        dict(row)
        for row in original["sources"]
        if row.get("source_id") in referenced_sources
    ]
    source_ids = {row.get("source_id") for row in kept_sources}
    missing_sources = sorted(referenced_sources - source_ids)
    if missing_sources:
        raise QuarantineError(f"retained canonical rows reference missing sources: {missing_sources}")

    rewritten = {
        "sources": kept_sources,
        "entities": kept_entities,
        "relationships": candidate_relationships,
        "alerts": kept_alerts,
    }
    for stream in STREAM_ORDER:
        _write_jsonl(federation_dir / f"{stream}.jsonl", rewritten[stream])

    files: list[dict[str, Any]] = []
    for stream in STREAM_ORDER:
        path = federation_dir / f"{stream}.jsonl"
        files.append({
            "filename": path.name,
            "stream": stream,
            "record_count": len(rewritten[stream]),
            "sha256": _sha256(path),
            "schema_id": STREAM_SCHEMA[stream],
        })
    mode = manifest.get("mode")
    if not isinstance(mode, str) or not mode:
        raise QuarantineError("canonical manifest mode is required")
    digest = hashlib.sha256(
        ("|".join(f"{entry['filename']}:{entry['sha256']}" for entry in files) + f"|{mode}").encode()
    ).hexdigest()[:32]
    manifest["package_id"] = f"pkg_{digest}"
    manifest["files"] = files
    manifest["review_quarantine_policy"] = POLICY_VERSION
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    quarantined = quarantined_assets + quarantined_events + quarantined_alerts
    state_counts = Counter(item["review_status"] for item in quarantined)
    receipt = {
        "schema_version": "aguayluz_federation_review_quarantine_v1",
        "policy_version": POLICY_VERSION,
        "producer": PRODUCER,
        "state": "PASS",
        "canonical_admission_rule": "ACCEPTED_ONLY",
        "legacy_aliases": {"approved": "accepted"},
        "raw_counts": {
            "assets": len(assets),
            "events": len(events),
            "alerts": len(alerts),
        },
        "accepted_input_counts": {
            "assets": len(accepted_assets),
            "events": len(accepted_events),
            "alerts": len(accepted_alerts),
        },
        "quarantined_input_counts": {
            "assets": len(quarantined_assets),
            "events": len(quarantined_events),
            "alerts": len(quarantined_alerts),
            "by_state": dict(sorted(state_counts.items())),
            "total": len(quarantined),
        },
        "legacy_alias_count": alias_assets + alias_events + alias_alerts,
        "quarantined": quarantined,
        "canonical_counts_before": {stream: len(original[stream]) for stream in STREAM_ORDER},
        "canonical_counts_after": {stream: len(rewritten[stream]) for stream in STREAM_ORDER},
        "invariants": {
            "input_arithmetic_closed": (
                len(assets) + len(events) + len(alerts)
                == len(accepted_assets) + len(accepted_events) + len(accepted_alerts) + len(quarantined)
            ),
            "quarantined_primary_entities_absent": not bool(
                quarantined_primary & {row.get("entity_id") for row in kept_entities}
            ),
            "canonical_alerts_accepted_only": len(kept_alerts) == len(accepted_alerts),
            "relationship_endpoints_retained": all(
                row.get("source_entity_id") in kept_entity_ids
                and row.get("target_entity_id") in kept_entity_ids
                for row in candidate_relationships
            ),
        },
        "problems": [],
    }
    if not all(receipt["invariants"].values()):
        raise QuarantineError(f"quarantine invariant failed: {receipt['invariants']}")
    (outputs_dir / "review_quarantine_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs", type=Path, default=Path("outputs"))
    parser.add_argument("--federation-dir", type=Path, default=Path("outputs/federation"))
    args = parser.parse_args(argv)
    try:
        receipt = enforce(args.outputs, args.federation_dir)
    except Exception as exc:  # noqa: BLE001 - fail closed
        print(json.dumps({"state": "BLOCKED", "problems": [f"{type(exc).__name__}: {exc}"]}, indent=2))
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
