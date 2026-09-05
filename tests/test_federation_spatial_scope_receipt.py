from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _load_module():
    path = ROOT / "scripts" / "write_federation_spatial_scope_receipt.py"
    spec = importlib.util.spec_from_file_location("scope_receipt", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scope_receipt_binds_exact_tracked_policy_bytes():
    module = _load_module()
    receipt = module.build_receipt()

    scope_path = ROOT / receipt["scope_path"]
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(scope_path.read_bytes()).hexdigest()

    assert receipt["state"] == "PASS"
    assert receipt["claim"] == "FEDERATION_SPATIAL_ARCHITECTURE"
    assert receipt["producer_repository"] == "jotaele44/aguayluz-pr"
    assert HEX40.fullmatch(receipt["producer_commit"])
    assert HEX40.fullmatch(receipt["producer_tree"])
    assert HEX40.fullmatch(receipt["scope_git_blob_sha"])
    assert HEX64.fullmatch(receipt["scope_sha256"])
    assert receipt["scope_sha256"] == digest
    assert receipt["scope_bytes"] == scope_path.stat().st_size
    assert receipt["scope_status"] == scope["status"]
    assert receipt["problems"] == []
