#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; REPO="aguayluz-pr"; FORBIDDEN=("AdminKit","federation-admin-workstation","lockstep.override","certification.issue","deployment.promote","PRII_MANAGER_BOOTSTRAP_NONCE")
def fail(m): print("ADMIN_BOUNDARY_FAIL: "+m,file=sys.stderr); raise SystemExit(1)
m=json.loads((ROOT/".federation/admin-boundary.json").read_text()); e={"schema_version":"thehub_admin_boundary_consumer_v1","contract_version":"1.0.0","repository":REPO,"plane":"BOUNDED_OPERATIONAL","federation_global_admin":False,"token_audience":"repository-operation","hub_outage_behavior":"LOCAL_OPERATIONS_CONTINUE_GLOBAL_MUTATIONS_FAIL_CLOSED","admin_kit_allowed":False}
if m!=e: fail("manifest differs from exact bounded-operational contract")
p=subprocess.run(["git","ls-files"],cwd=ROOT,check=True,text=True,capture_output=True).stdout.splitlines(); n=0
for r in p:
    if r.startswith(("docs/","reports/","tests/",".federation/")) or r=="scripts/check_admin_boundary.py" or Path(r).suffix.lower() not in {".py",".js",".jsx",".ts",".tsx",".swift",".java",".kt",".go",".rs",".yml",".yaml"}: continue
    t=(ROOT/r).read_text(encoding="utf-8",errors="ignore"); n+=1; h=next((x for x in FORBIDDEN if x in t),None)
    if h: fail(f"{r}: prohibited federation-admin capability marker {h!r}")
print(f"ADMIN_BOUNDARY_PASS repo={REPO} scanned={n}")
