#!/usr/bin/env python3
"""Durably ingest one idempotent Centinelas handoff envelope, then promote it.

Supported envelope kinds:
- environmental_signal (default/backward compatible) -> service_events.jsonl
- access_condition -> access_conditions.jsonl

Receipts remain content-addressed by idempotency_key. Duplicate deliveries are
acknowledged without re-promoting. Access conditions preserve T1 evidence and
cannot carry geometry; exact geometry binding is registry-controlled downstream.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from jsonschema import validate

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_centinelas_dispatch import payload_to_event  # noqa: E402
from ingest_news_event import OUT_DEFAULT, _read_jsonl, _write_jsonl  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RECEIPTS_DEFAULT = REPO / "data" / "centinelas_handoffs"
ACCESS_OUT_DEFAULT = REPO / "data" / "access_conditions.jsonl"
_ACCESS_SCHEMA = REPO / "schemas" / "access_condition.v1.schema.json"
_ACCESS_BINDINGS = REPO / "data" / "reference" / "el_yunque_access_asset_bindings.json"
_FORBIDDEN_GEOMETRY_KEYS = {
    "geometry", "coordinates", "latitude", "longitude", "bbox", "bounding_box",
    "polygon", "polyline", "centroid", "geojson",
}


def receipt_path(idempotency_key: str, receipts_dir: Path) -> Path:
    return receipts_dir / f"{hashlib.sha256(idempotency_key.encode()).hexdigest()}.json"


def write_receipt(payload: dict, receipts_dir: Path) -> tuple[Path, bool]:
    out = receipt_path(payload["idempotency_key"], receipts_dir)
    duplicate = out.exists()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not duplicate:
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out, duplicate


def _read_access_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_access_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _access_binding(asset_key: str | None) -> tuple[str | None, str]:
    if not asset_key:
        return None, "unbound_no_asset_key"
    registry = json.loads(_ACCESS_BINDINGS.read_text(encoding="utf-8"))["bindings"]
    entry = registry.get(asset_key)
    if not entry:
        return None, "unbound_unknown_asset_key"
    asset_id = entry.get("certified_asset_id")
    if not asset_id:
        return None, "unbound_no_certified_geometry"
    return str(asset_id), "bound_certified_geometry"


def _validate_access_signal(signal: dict) -> None:
    forbidden = sorted(_FORBIDDEN_GEOMETRY_KEYS.intersection(signal))
    if forbidden:
        raise ValueError(f"access-condition payload must not carry geometry fields: {forbidden}")
    schema = json.loads(_ACCESS_SCHEMA.read_text(encoding="utf-8"))
    validate(instance=signal, schema=schema)
    if signal.get("evidence_tier") != "T1":
        raise ValueError("El Yunque official access condition must preserve T1 evidence")


def _promote_access_condition(signal: dict, out: Path = ACCESS_OUT_DEFAULT) -> dict:
    _validate_access_signal(signal)
    bound_asset_id, binding_status = _access_binding(signal.get("asset_key"))
    row = dict(signal)
    row["bound_asset_id"] = bound_asset_id
    row["binding_status"] = binding_status
    existing = {item["condition_id"]: item for item in _read_access_jsonl(out)}
    existing[row["condition_id"]] = row
    _write_access_jsonl(out, list(existing.values()))
    return row


def promote_signal(
    payload: dict,
    events_out: Path,
    access_out: Path = ACCESS_OUT_DEFAULT,
) -> tuple[str | None, str | None]:
    signal = payload.get("signal")
    if not isinstance(signal, dict) or not signal:
        return None, None

    kind = payload.get("kind") or signal.get("kind") or "environmental_signal"
    if kind == "access_condition":
        row = _promote_access_condition(signal, access_out)
        return None, row["condition_id"]
    if kind not in {"environmental_signal", "signal"}:
        raise ValueError(f"unsupported Centinelas handoff kind: {kind}")

    row = payload_to_event(signal)
    by_id = {e["event_id"]: e for e in _read_jsonl(events_out)}
    by_id[row["event_id"]] = row
    _write_jsonl(events_out, list(by_id.values()))
    return row["event_id"], None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipts-dir", default=str(RECEIPTS_DEFAULT))
    ap.add_argument("--events-out", default=str(OUT_DEFAULT))
    ap.add_argument("--access-out", default=str(ACCESS_OUT_DEFAULT))
    args = ap.parse_args()

    payload = json.loads(os.environ["CENTINELAS_CLIENT_PAYLOAD"])
    if payload["target"] != os.environ["EXPECTED_TARGET"]:
        raise SystemExit("handoff target mismatch")

    out, duplicate = write_receipt(payload, Path(args.receipts_dir))
    promoted_event = None
    promoted_condition = None
    if not duplicate:
        promoted_event, promoted_condition = promote_signal(
            payload, Path(args.events_out), Path(args.access_out)
        )

    print(f"receipt {'exists' if duplicate else 'written'}: {out}")
    if promoted_condition:
        print(f"promoted to access_conditions: {promoted_condition}")
    elif promoted_event:
        print(f"promoted to service_events: {promoted_event}")
    elif not duplicate:
        print("no `signal` in envelope — receipt stored, nothing to promote")

    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(
                f"duplicate={str(duplicate).lower()}\n"
                f"receipt_path={out}\n"
                f"promoted_event_id={promoted_event or ''}\n"
                f"promoted_condition_id={promoted_condition or ''}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
