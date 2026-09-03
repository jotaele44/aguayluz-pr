#!/usr/bin/env python3
import csv, hashlib, json, sys, zipfile
from pathlib import Path

def main(zpath):
    zpath = Path(zpath)
    result = {"zip": str(zpath), "sha256": hashlib.sha256(zpath.read_bytes()).hexdigest(), "tables": [], "failures": []}
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 68:
            result["failures"].append(f"expected 68 CSVs, got {len(names)}")
        for n in sorted(names):
            b = z.read(n)
            try:
                s = b.decode("utf-8-sig")
            except UnicodeDecodeError:
                result["failures"].append(f"{n}: not UTF-8/BOM compatible")
                continue
            rows = list(csv.reader(s.splitlines()))
            header = rows[0] if rows else []
            bad = sum(1 for r in rows[1:] if len(r) != len(header))
            dup = [h for h in set(header) if header.count(h) > 1]
            if bad:
                result["failures"].append(f"{n}: {bad} width mismatches")
            if dup:
                result["failures"].append(f"{n}: duplicate headers {dup}")
            result["tables"].append({"file": n, "rows": max(0, len(rows)-1), "columns": len(header), "sha256": hashlib.sha256(b).hexdigest()})
    result["status"] = "PASS" if not result["failures"] else "FAIL"
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
