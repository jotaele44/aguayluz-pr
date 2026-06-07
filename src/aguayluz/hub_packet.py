"""Build the self-contained `HubPacket` artifact for thehub-pr ingestion.

Whereas the M15 federation handoffs are one-file-per-receiver and reference
the producer's outputs/ by path, a hub packet inlines everything a receiver
needs: the Base44 envelope, every per-target FederationHandoff, the asset +
event records, the bridge summary, and a reconciliation summary. A SHA-256
signature over the canonical (sorted-keys) JSON of envelope+handoffs+entities
lets the receiver verify integrity without contacting the producer.

The signature is deterministic — same inputs always produce the same hash.
That property is the contract the hub depends on for content-addressed
caching: two packets with identical signatures need to be processed only
once.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PACKET_VERSION = "1.0"


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _load_handoffs(outputs_dir: Path) -> list[dict[str, Any]]:
    """Inline every `handoff_<target>.json` file the M15 vector emitted."""
    handoffs: list[dict[str, Any]] = []
    for path in sorted(outputs_dir.glob("handoff_*.json")):
        handoffs.append(_load(path, {}))
    return handoffs


def _reconciliation_summary(report: dict[str, Any] | None) -> dict[str, int]:
    """Project the M8 report to a counts-only summary (entities array keeps the
    packet small even when findings runs into the hundreds)."""
    base = {"consistent_count": 0, "status_mismatches": 0, "missing_coverage": 0, "stale_assets": 0}
    if not isinstance(report, dict):
        return base
    summary = report.get("summary") or {}
    for k in base:
        v = summary.get(k)
        if isinstance(v, int):
            base[k] = v
    return base


def _canonical_serialize(payload: dict[str, Any]) -> bytes:
    """Sort all keys recursively + drop whitespace so the hash is stable.

    `json.dumps(sort_keys=True)` only sorts the top level when the values are
    plain dicts; we want recursive ordering of arrays too so re-ordering on
    disk doesn't break the hash. JSON dump with sort_keys + separators=(',',':')
    is sufficient for our shape (no nested arrays of objects that need
    re-ordering — the handoffs array is intentionally ordered).
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_hub_packet(
    *,
    outputs_dir: Path,
    run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build a HubPacket dict from current outputs/. Caller is responsible for
    validating against `schemas/hub_packet.schema.json` and writing the file."""
    envelope = _load(outputs_dir / "base44_export.json", {})
    handoffs = _load_handoffs(outputs_dir)
    utility_assets = _load(outputs_dir / "utility_assets.json", [])
    service_events = _load(outputs_dir / "service_events.json", [])
    bridge_summary = _load(outputs_dir / "bridge_summary.json", None)
    reconciliation = _load(outputs_dir / "reconciliation_report.json", None)

    entities = {
        "utility_assets": utility_assets,
        "service_events": service_events,
        "bridge_summary": bridge_summary,
        "reconciliation_summary": _reconciliation_summary(reconciliation),
    }

    signed_body = {
        "envelope": envelope,
        "handoffs": handoffs,
        "entities": entities,
    }
    signature = hashlib.sha256(_canonical_serialize(signed_body)).hexdigest()

    return {
        "packet_version": PACKET_VERSION,
        "module_id": "aguayluz-pr",
        "run_id": run_id,
        "generated_at": generated_at,
        "signature_sha256": signature,
        "envelope": envelope,
        "handoffs": handoffs,
        "entities": entities,
    }


def verify_packet_signature(packet: dict[str, Any]) -> bool:
    """Recompute the signature and compare. Returns True on intact, False on
    tamper. Receivers call this on inbound packets before trusting any field."""
    signed_body = {
        "envelope": packet.get("envelope", {}),
        "handoffs": packet.get("handoffs", []),
        "entities": packet.get("entities", {}),
    }
    expected = hashlib.sha256(_canonical_serialize(signed_body)).hexdigest()
    return expected == packet.get("signature_sha256")
