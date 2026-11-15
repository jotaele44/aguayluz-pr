"""scripts/ingest_hydro_names.py offline, on rows copied from the real GNIS Puerto Rico file."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

from aguayluz import hydro_inventory as hi

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "hydro_inventory"

_SPEC = importlib.util.spec_from_file_location("ingest_hydro_names", REPO / "scripts" / "ingest_hydro_names.py")
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest
_SPEC.loader.exec_module(ingest)


def run(data_dir, src=FIXTURES):
    return ingest.main(["--src-dir", str(src), "--data-dir", str(data_dir), "--now", "2026-11-15T02:00:00Z"])


def test_hydrographic_classes_are_claimed_and_every_other_row_is_counted(tmp_path):
    assert run(tmp_path) == 0
    claims = hi.read_claims(tmp_path / hi.HYDRO_DIR / "claims_gnis_names.jsonl")
    assert {c["feature_type"] for c in claims} == {"spring", "watercourse", "reservoir"}
    assert sum(1 for c in claims if c["feature_type"] == "spring") == 2
    ledger = json.loads((tmp_path / hi.HYDRO_DIR / "ingest_names_receipt.json").read_text())["ledgers"]["usgs_gnis_names"]
    assert ledger["source"] == 11 and ledger["retained"] == 7 and ledger["delta"] == 0
    assert ledger["excluded_by_reason"] == {"GNIS class 'Populated Place' is not hydrographic": 4}


def test_a_changed_table_layout_stops_the_run(tmp_path):
    # CONSTRUCTED: the GNIS table without its coordinate columns.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Text/DomesticNames_PR.txt", "feature_id|feature_name|feature_class\n1|X|Spring\n")
    src = tmp_path / "src"
    src.mkdir()
    (src / "DomesticNames_PR_Text.zip").write_bytes(buf.getvalue())
    data = tmp_path / "data"
    assert run(data, src) == 1
    receipt = json.loads((data / hi.HYDRO_DIR / "ingest_names_receipt.json").read_text())
    assert receipt["last_status"] == "FAIL" and "columns changed" in receipt["last_error"]
