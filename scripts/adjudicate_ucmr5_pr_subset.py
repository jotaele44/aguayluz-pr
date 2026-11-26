#!/usr/bin/env python3
"""Adjudicate two UCMR5 Puerto Rico TSV manifestations without assuming byte identity."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[str], Counter[str], set[str]]:
    raw=path.read_text(encoding="utf-8")
    lines=raw.splitlines()
    if not lines:
        raise ValueError(f"empty TSV: {path}")
    reader=csv.DictReader(lines, delimiter="\t")
    if reader.fieldnames is None:
        raise ValueError(f"missing header: {path}")
    header=list(reader.fieldnames)
    pws_field=next((h for h in header if h.lower().replace(" ","")=="pwsid"),None)
    if pws_field is None:
        raise ValueError(f"PWSID missing: {path}")
    rows=[row for row in reader]
    canon=[]
    pws=set()
    for row in rows:
        canon.append("\t".join(str(row.get(h) or "") for h in header))
        p=str(row.get(pws_field) or "").strip().upper()
        if p:
            pws.add(p)
    return header, canon, Counter(canon), pws


def adjudicate(old: Path, new: Path) -> dict[str, Any]:
    old_sha,new_sha=sha256_file(old),sha256_file(new)
    oh,orows,oc,opws=read_tsv(old)
    nh,nrows,nc,npws=read_tsv(new)
    headers_equal=oh==nh
    intersection=sum((oc & nc).values()) if headers_equal else 0
    old_only=sum((oc-nc).values()) if headers_equal else len(orows)
    new_only=sum((nc-oc).values()) if headers_equal else len(nrows)
    union=sum((oc|nc).values()) if headers_equal else len(orows)+len(nrows)
    sym=old_only+new_only
    if old_sha==new_sha:
        state="BYTE_IDENTICAL"
    elif headers_equal and oc==nc:
        state="LOGICALLY_IDENTICAL_ROW_MULTISET"
    else:
        state="DISTINCT_PR_SUBSET"
    return {
      "schema_version":"aguayluz.pfas.ucmr5_pr_subset_adjudication/v1",
      "classification":state,
      "old":{"sha256":old_sha,"rows":len(orows),"pwsids":len(opws)},
      "new":{"sha256":new_sha,"rows":len(nrows),"pwsids":len(npws)},
      "headers_equal":headers_equal,
      "row_multiset":{"intersection":intersection,"old_only":old_only,"new_only":new_only,"union":union,"symmetric_difference":sym},
      "pwsid_set":{
        "intersection":len(opws & npws),
        "old_only":sorted(opws-npws),
        "new_only":sorted(npws-opws),
        "union":len(opws|npws),
        "symmetric_difference":len(opws^npws),
      },
    }


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("old_tsv",type=Path)
    p.add_argument("new_tsv",type=Path)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    try:
        r=adjudicate(args.old_tsv,args.new_tsv)
    except Exception as exc:  # noqa: BLE001
        r={"schema_version":"aguayluz.pfas.ucmr5_pr_subset_adjudication/v1","classification":"UNRESOLVED","error":str(exc)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(r,indent=2,sort_keys=True))
    return 0 if r["classification"]!="UNRESOLVED" else 1


if __name__=="__main__":
    raise SystemExit(main())
