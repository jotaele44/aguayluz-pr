from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_validator():
    path = ROOT / "scripts" / "validate_federation_gis_retention.py"
    spec = importlib.util.spec_from_file_location("validate_federation_gis_retention", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_merged_gis_change_set_is_retained_20_of_20():
    validator = _load_validator()
    ledger = json.loads(
        (ROOT / "governance" / "federation_gis_retention_v1.json").read_text(encoding="utf-8")
    )
    result = validator.validate_retention(ledger)
    assert result["ok"], result["problems"]
    assert result["expected"] == 20
    assert result["present"] == 20
    assert result["missing"] == []
    assert result["source_merge_changed_paths"] == [
        ".federation/gui-capabilities.json",
        "schemas/federation_spatial_manifest_v1.schema.json",
        "scripts/validate_federation_spatial.py",
    ]
    assert result["repair_changed_paths"] == [
        "schemas/federation_spatial_manifest_v1.schema.json",
        "scripts/validate_federation_spatial.py",
    ]
