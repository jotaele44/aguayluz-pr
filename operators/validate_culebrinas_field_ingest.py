#!/usr/bin/env python3
import json, sys, hashlib
from pathlib import Path
try:
    import jsonschema
except ImportError:
    jsonschema = None
BASE = Path(__file__).resolve().parents[1]
SCHEMA = json.load(open(BASE / "data/culebrinas/frontier/v2/field_observation_ingest_schema_v2.json"))
def stable_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
def validate(obj):
    if jsonschema:
        jsonschema.validate(obj, SCHEMA)
    else:
        missing = [k for k in SCHEMA["required"] if k not in obj]
        if missing:
            raise ValueError("missing:" + ",".join(missing))
    return stable_hash(obj)
def main(path):
    objects = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    ids = set()
    for rownum, obj in enumerate(objects, 1):
        digest = validate(obj)
        oid = obj["observation_id"]
        if oid in ids:
            raise SystemExit(f"duplicate observation_id at row {rownum}")
        ids.add(oid)
        print(oid, digest)
if __name__ == "__main__":
    main(sys.argv[1])
