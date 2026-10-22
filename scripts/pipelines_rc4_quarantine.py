"""RC4 Pipelines quarantine validator. No canonical export or deployment side effects."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

LANES = {"spiderweb-pr", "aguayluz-pr", "PITIRRE", "PRIIS-MII", "TGIC-PR"}
REQUIRED = {"asset_id", "asset_sha256", "classification", "canonical_entity_id", "geometry", "publishable", "foia_submitted"}

def verify(folder: Path, lane: str) -> dict:
    if lane not in LANES:
        raise ValueError("Unknown source lane")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("publication_gate") != "DENY":
        raise ValueError("Publication gate must be DENY")
    meta = manifest.get("files", {}).get(lane + ".jsonl")
    if not isinstance(meta, dict):
        raise ValueError("Missing lane metadata")
    path = folder / (lane + ".jsonl")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != meta.get("sha256") or len(data) != meta.get("size"):
        raise ValueError("Payload integrity mismatch")
    seen = set()
    count = 0
    for lineno, line in enumerate(data.splitlines(), 1):
        if not line.strip():
            raise ValueError("Blank record line")
        row = json.loads(line)
        if not REQUIRED.issubset(row):
            raise ValueError("Missing required fields at line %s" % lineno)
        if (row["canonical_entity_id"] is not None or row["geometry"] is not None or
            row["publishable"] is not False or row["foia_submitted"] is not False or
            row["classification"] != "CANDIDATE_NOT_IDENTITY"):
            raise ValueError("Unsafe attempted promotion at line %s" % lineno)
        if not isinstance(row["asset_id"], str) or not isinstance(row["asset_sha256"], str):
            raise ValueError("Invalid provenance")
        count += 1
    return {"lane": lane, "rows_verified": count, "payload_sha256": meta["sha256"], "status": "AUDIT_ONLY", "canonical_promoted": 0, "source_path": str(path)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exports", required=True, type=Path)
    parser.add_argument("--lane", required=True, choices=sorted(LANES))
    args = parser.parse_args()
    print(json.dumps(verify(args.exports, args.lane), sort_keys=True))
