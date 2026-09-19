#!/usr/bin/env python3
"""Normalize the MiLUMA regional customer-status snapshot with exact provenance.

The regionsWithoutService endpoint is an aggregate snapshot, not a discrete outage
event. Keep it in its own typed dataset so regional customer counts are never
promoted into event identity.

Input provenance is accepted only when the MiLUMA fetch receipt says the regional
endpoint is PASS and the exact source-byte SHA-256 matches the receipt. A source
access failure is a clean skip; a hash/schema/arithmetic contradiction fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.models import validate_against_schema  # noqa: E402

DEFAULT_SRC = "/tmp/luma_regions.json"
DEFAULT_META = "/tmp/luma_snapshot_manifest.json"
DEFAULT_OUT = "data/luma_region_status.jsonl"


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize(raw: str) -> str:
    folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    return " ".join(folded.upper().split())


def _slug(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", _normalize(raw)).strip("_") or "UNKNOWN"


def _stamp(observed_at: str) -> str:
    return observed_at.replace("-", "").replace(":", "").replace("+00:00", "Z")


def resolve_receipt(src: Path, meta_path: Path) -> tuple[str, str, str] | None:
    """Return observed_at/source_ref/source_hash, or None for a recorded source gap."""
    if not meta_path.is_file():
        print(f"regional-source-unavailable: snapshot manifest missing ({meta_path}); skipping")
        return None

    doc = json.loads(meta_path.read_text(encoding="utf-8"))
    entry = doc.get("regions")
    if not isinstance(entry, dict):
        raise ValueError("snapshot manifest lacks regions entry")
    if entry.get("status") != "PASS":
        state = entry.get("status", "UNRESOLVED")
        detail = entry.get("error", "")
        print(f"regional-source-{str(state).lower()}: {detail}; skipping")
        return None

    if not src.is_file():
        raise ValueError(f"regions receipt is PASS but source bytes are missing: {src}")

    observed_at = entry.get("retrieval_utc")
    source_ref = entry.get("url")
    source_hash = entry.get("response_sha256")
    if not all(isinstance(v, str) and v for v in (observed_at, source_ref, source_hash)):
        raise ValueError("PASS regions receipt lacks retrieval_utc/url/response_sha256")

    actual = _sha256_path(src)
    if actual != source_hash:
        raise ValueError(f"regional source hash mismatch: manifest={source_hash} actual={actual}")
    return observed_at, source_ref, source_hash


def build_rows(
    doc: dict[str, Any],
    observed_at: str,
    source_ref: str,
    source_hash: str,
) -> list[dict[str, Any]]:
    regions = doc.get("regions")
    if not isinstance(regions, list):
        raise ValueError("MiLUMA regional payload lacks a regions list")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_row in regions:
        if not isinstance(source_row, dict):
            raise ValueError("MiLUMA regional row is not an object")
        region_raw = source_row.get("name")
        total = source_row.get("totalClients")
        affected = source_row.get("totalClientsWithoutService")

        if not isinstance(region_raw, str) or not region_raw.strip():
            raise ValueError("MiLUMA regional row lacks a valid name")
        region_normalized = _normalize(region_raw)
        if region_normalized in seen:
            raise ValueError(f"duplicate normalized MiLUMA region: {region_raw!r}")
        seen.add(region_normalized)

        for field, value in (("totalClients", total), ("totalClientsWithoutService", affected)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{region_raw}: non-numeric {field}")
            if value < 0 or int(value) != value:
                raise ValueError(f"{region_raw}: invalid {field}={value!r}")

        total_i = int(total)
        affected_i = int(affected)
        if affected_i > total_i:
            raise ValueError(
                f"{region_raw}: affected_customers={affected_i} exceeds total_customers={total_i}"
            )
        affected_pct = round((affected_i / total_i) * 100, 6) if total_i else 0.0
        if total_i == 0 and affected_i != 0:
            raise ValueError(f"{region_raw}: zero denominator with non-zero affected customers")

        row = {
            "status_id": f"AYL_LUMA_REGION_{_stamp(observed_at)}_{_slug(region_raw)}",
            "region_raw": region_raw,
            "region_normalized": region_normalized,
            "total_customers": total_i,
            "affected_customers": affected_i,
            "affected_pct": affected_pct,
            "observed_at": observed_at,
            "source_ref": source_ref,
            "source_hash": source_hash,
            "evidence_tier": "T2",
            "confidence": 80,
            "review_status": "needs_review",
        }
        validate_against_schema("luma_region_status", row)
        rows.append(row)

    if len({row["status_id"] for row in rows}) != len(rows):
        raise ValueError("regional status_id collision")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--snapshot-meta", default=DEFAULT_META)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    # Never retain an older live regional snapshot after a source-access/schema failure.
    out.unlink(missing_ok=True)
    try:
        receipt = resolve_receipt(src, Path(args.snapshot_meta))
        if receipt is None:
            return 0
        observed_at, source_ref, source_hash = receipt
        doc = json.loads(src.read_text(encoding="utf-8"))
        rows = build_rows(doc, observed_at, source_ref, source_hash)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"regional-ingest-invalid: {exc}", file=sys.stderr)
        return 2

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    total = sum(row["total_customers"] for row in rows)
    affected = sum(row["affected_customers"] for row in rows)
    print(
        f"wrote {len(rows)} MiLUMA regional status rows -> {out}; "
        f"customers={total}, affected={affected}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
