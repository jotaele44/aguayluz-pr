#!/usr/bin/env python3
"""Strict validator for real authorized Culebrinas field observations.

This validator accepts OBSERVED evidence only. Templates, proposed stations,
model output and inferred values are rejected by schema before ingestion.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    jsonschema = None

BASE = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((BASE / "data/culebrinas/frontier/v2/field_observation_ingest_schema_v3.json").read_text())


def stable_hash(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def validate(obj: dict) -> str:
    if jsonschema:
        validator = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
        validator.validate(obj)
    else:
        missing = [k for k in SCHEMA["required"] if k not in obj]
        if missing:
            raise ValueError("missing:" + ",".join(missing))
        if obj.get("evidence_state") != "OBSERVED" or obj.get("geometry_state") != "OBSERVED":
            raise ValueError("nonobserved_evidence_prohibited")
    value = obj.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(float(value)):
        raise ValueError("nonfinite_value")
    detection = obj.get("detection_limit")
    if isinstance(detection, (int, float)) and not isinstance(detection, bool) and not math.isfinite(float(detection)):
        raise ValueError("nonfinite_detection_limit")
    if obj.get("identity_state") in {"CANDIDATE_NOT_IDENTITY", "UNRESOLVED"}:
        raise ValueError("unresolved_identity_not_admissible_to_experimental_store")
    geometry = obj.get("geometry")
    if not isinstance(geometry, dict) or not geometry:
        raise ValueError("observed_geometry_required")
    if not obj.get("survey_crs") or not obj.get("survey_datum"):
        raise ValueError("survey_control_required")
    return stable_hash(obj)


def main(path: str) -> None:
    objects = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not objects:
        raise SystemExit("no_observations")
    ids: set[str] = set()
    for rownum, obj in enumerate(objects, 1):
        try:
            digest = validate(obj)
        except Exception as exc:
            raise SystemExit(f"row {rownum}: {exc}") from exc
        oid = obj["observation_id"]
        if oid in ids:
            raise SystemExit(f"duplicate observation_id at row {rownum}")
        ids.add(oid)
        print(oid, digest)


if __name__ == "__main__":
    main(sys.argv[1])
