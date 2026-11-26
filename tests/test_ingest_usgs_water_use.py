"""scripts/ingest_usgs_water_use.py end to end, offline.

Inputs are the real USGS data-release files (byte-identical, SHA-256 pinned in
config/usgs_water_use_sources.v1.json). Cases that need bytes USGS did not publish (a
changed release, a missing file) are CONSTRUCTED and say so.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from aguayluz import water_use as wu

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "usgs_water_use"
SCHEMAS = REPO / "schemas" / "water-use" / "v1"
NOW = "2026-11-14T07:00:00Z"
LATER = "2026-11-21T07:00:00Z"

_SPEC = importlib.util.spec_from_file_location(
    "ingest_usgs_water_use", REPO / "scripts" / "ingest_usgs_water_use.py"
)
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest
_SPEC.loader.exec_module(ingest)


def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def run(data_dir, *extra, src=FIXTURES, now=NOW):
    return ingest.main(["--src-dir", str(src), "--data-dir", str(data_dir), "--now", now, *extra])


def receipt(data_dir):
    return json.loads((Path(data_dir) / wu.RECEIPT_FILE).read_text())


def test_offline_run_closes_arithmetic_and_validates_against_the_schemas(tmp_path):
    assert run(tmp_path) == 0
    rows = wu.load_estimates(tmp_path)
    check = validator("water_use_estimate.schema.json")
    for row in rows:
        assert list(check.iter_errors(row)) == [], row["record_id"]
    rc = receipt(tmp_path)
    assert list(validator("water_use_receipt.schema.json").iter_errors(rc)) == []
    assert rc["last_status"] == "PASS" and rc["last_error"] is None
    success = rc["last_success"]
    assert success["records_written"] == len(rows) == 207
    assert success["years"] == [2010, 2015, 2020]
    assert [s["source_key"] for s in success["sources"]] == [
        "ps_municipio_2020", "ps_municipio_2015", "category_2015", "irrigation_2015", "trends_2015",
        "ofr_2014_1117",
    ]
    for source in success["sources"]:
        assert source["arithmetic"]["state"] == "PASS" and source["arithmetic"]["delta"] == 0
        assert source["arithmetic"]["unresolved"] == 0 and source["pin_matches"] is True
    assert len({r["record_id"] for r in rows}) == len(rows)


def test_the_two_2015_tables_must_agree_on_public_supply(tmp_path):
    assert run(tmp_path) == 0
    assert receipt(tmp_path)["last_success"]["cross_source_agreements"] == [
        {"record_id": "WU:2015:public_supply:island:all", "kept": "ps_municipio_2015", "agrees": "category_2015"}
    ]


def test_the_raw_bytes_are_frozen_before_parsing(tmp_path):
    assert run(tmp_path) == 0
    names = {p.name for p in (tmp_path / wu.SNAPSHOT_DIRNAME).iterdir()}
    config = wu.load_sources(REPO / "config")
    assert names == {f"{s['pinned_sha256']}.xlsx" for s in config["sources"]}


def test_committed_data_equals_a_fresh_offline_run(tmp_path):
    assert run(tmp_path) == 0
    fresh = (tmp_path / wu.ESTIMATES_FILE).read_text(encoding="utf-8")
    assert fresh == (REPO / "data" / wu.ESTIMATES_FILE).read_text(encoding="utf-8")
    committed = json.loads((REPO / "data" / wu.RECEIPT_FILE).read_text(encoding="utf-8"))
    assert list(validator("water_use_receipt.schema.json").iter_errors(committed)) == []
    assert committed["last_status"] == "PASS"


def test_a_rerun_is_byte_identical(tmp_path):
    assert run(tmp_path) == 0
    first = (tmp_path / wu.ESTIMATES_FILE).read_bytes()
    assert run(tmp_path, now=LATER) == 0
    assert (tmp_path / wu.ESTIMATES_FILE).read_bytes() == first


def test_dry_run_writes_nothing(tmp_path, capsys):
    assert run(tmp_path, "--dry-run") == 0
    assert list(tmp_path.iterdir()) == []
    assert json.loads(capsys.readouterr().out)["records_written"] == 207


def _changed_release(tmp_path) -> Path:
    """CONSTRUCTED: the fixtures with one file's bytes altered (a trailing byte)."""
    src = tmp_path / "src"
    shutil.copytree(FIXTURES, src)
    target = src / "ps_municipio_2020.xlsx"
    target.write_bytes(target.read_bytes() + b"\n")
    return src


def test_changed_bytes_fail_and_keep_the_previous_success(tmp_path):
    data = tmp_path / "data"
    assert run(data) == 0
    before = (data / wu.ESTIMATES_FILE).read_bytes()
    assert run(data, src=_changed_release(tmp_path), now=LATER) == 1
    rc = receipt(data)
    assert rc["last_status"] == "FAIL" and "differs from the pin" in rc["last_error"]
    assert rc["last_success_utc"] == NOW and rc["last_success"]["records_written"] == 207
    assert (data / wu.ESTIMATES_FILE).read_bytes() == before
    assert list(validator("water_use_receipt.schema.json").iter_errors(rc)) == []


def test_a_missing_file_fails_closed(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(FIXTURES, src)
    (src / "trends_2015.xlsx").unlink()
    data = tmp_path / "data"
    assert run(data, src=src) == 1
    assert "could not acquire trends_2015" in receipt(data)["last_error"]
    assert not (data / wu.ESTIMATES_FILE).exists()


def test_a_bad_clock_is_a_usage_error(tmp_path):
    assert run(tmp_path, now="yesterday") == 2
