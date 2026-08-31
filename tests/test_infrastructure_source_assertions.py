from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "ontology" / "tools" / "freeze_source_assertions.py"
SCHEMA = ROOT / "schemas" / "infrastructure_source_assertion.schema.json"


def load_tool():
    spec = importlib.util.spec_from_file_location("freeze_source_assertions", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_freezer_requires_explicit_nonzero_header_row(tmp_path: Path):
    tool = load_tool()
    src = tmp_path / "demo.csv"
    src.write_text("a,b\n1,2\n", encoding="utf-8")
    try:
        tool.freeze_source(src, header_row_number=0)
    except ValueError as exc:
        assert "header_row_number" in str(exc)
    else:
        raise AssertionError("expected invalid explicit header row to fail")


def test_source_freezer_preserves_raw_strings_and_byte_hash(tmp_path: Path):
    tool = load_tool()
    src = tmp_path / "demo.csv"
    raw = "preamble only\nName,Type,Note\n  EBAS  ,Estación de Bombas,área húmeda\n"
    src.write_bytes(raw.encode("utf-8"))
    assertions, manifest = tool.freeze_source(src, header_row_number=2, encoding="utf-8", delimiter=",")
    assert manifest["arithmetic"]["pass"] is True
    assert manifest["certification_state"] == "PASS"
    assert len(assertions) == 1
    row = assertions[0]
    assert row["raw_fields"]["Name"] == "  EBAS  "
    assert row["raw_fields"]["Type"] == "Estación de Bombas"
    assert row["raw_fields"]["Note"] == "área húmeda"
    assert row["source_sha256"] == tool.sha256_bytes(src.read_bytes())
    assert row["identity_effect"] == "none"


def test_source_freezer_rejects_duplicate_headers(tmp_path: Path):
    tool = load_tool()
    src = tmp_path / "dup.csv"
    src.write_text("a,a\n1,2\n", encoding="utf-8")
    try:
        tool.freeze_source(src, header_row_number=1, encoding="utf-8", delimiter=",")
    except ValueError as exc:
        assert "duplicate raw header" in str(exc)
    else:
        raise AssertionError("duplicate headers must fail closed")


def test_width_mismatch_is_preserved_as_open_residue(tmp_path: Path):
    tool = load_tool()
    src = tmp_path / "width.csv"
    src.write_text("a,b\n1,2\n3\n", encoding="utf-8")
    assertions, manifest = tool.freeze_source(src, header_row_number=1, encoding="utf-8", delimiter=",")
    assert len(assertions) == 1
    assert manifest["width_mismatch_rows"] == [3]
    assert manifest["certification_state"] == "OPEN"
    assert manifest["arithmetic"]["pass"] is True


def test_source_assertion_schema_is_valid_json_schema():
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
