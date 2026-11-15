"""scripts/ingest_hydro_sites.py end to end, offline, on real source excerpts.

The fixtures are cut from the real responses (USGS monitoring locations, the NWIS site
service, WQP and EPA SDWIS) of 2026-11-15. Failure cases are CONSTRUCTED by editing a copy.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

from aguayluz import hydro_inventory as hi

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "hydro_inventory"

_SPEC = importlib.util.spec_from_file_location("ingest_hydro_sites", REPO / "scripts" / "ingest_hydro_sites.py")
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest
_SPEC.loader.exec_module(ingest)


def run(data_dir, src=FIXTURES, *extra):
    return ingest.main(["--src-dir", str(src), "--data-dir", str(data_dir), "--now", "2026-11-15T02:00:00Z",
                        "--min-gw-sites", "10", *extra])


def test_offline_run_writes_every_claim_set_and_a_pass_receipt(tmp_path):
    assert run(tmp_path) == 0
    hydro = tmp_path / hi.HYDRO_DIR
    usgs = hi.read_claims(hydro / "claims_usgs_sites.jsonl")
    wqp = hi.read_claims(hydro / "claims_wqp_wells.jsonl")
    sdwis = hi.read_claims(hydro / "claims_sdwis_wells.jsonl")
    assert len(usgs) == 49 and len(wqp) == 52 and len(sdwis) == 8
    receipt = json.loads((hydro / "ingest_sites_receipt.json").read_text())
    assert receipt["status"] == "PASS"
    assert receipt["ledgers"]["usgs_monitoring_locations"]["cross_check"]["aquifer_code_differences"] == 0
    assert all(len(m["byte_sha256"]) == 64 for m in receipt["manifestations"])


def test_sdwis_wells_carry_no_location_and_eqb_wells_keep_their_identifier(tmp_path):
    assert run(tmp_path) == 0
    hydro = tmp_path / hi.HYDRO_DIR
    sdwis = hi.read_claims(hydro / "claims_sdwis_wells.jsonl")
    assert all(c["lat"] is None and c["attributes"]["location"] == "not published by SDWIS" for c in sdwis)
    wqp = {c["source_feature_id"]: c for c in hi.read_claims(hydro / "claims_wqp_wells.jsonl")}
    assert "PREQB_GW-CABO ROJO II" in wqp and wqp["PREQB_GW-CABO ROJO II"]["attributes"].get("usgs_site_no") is None


def test_usgs_services_that_disagree_stop_the_run(tmp_path):
    # CONSTRUCTED: drop one well from the legacy NWIS response.
    src = tmp_path / "src"
    shutil.copytree(FIXTURES, src)
    rdb = (src / "nwis_gw.rdb").read_text().splitlines()
    (src / "nwis_gw.rdb").write_text("\n".join(rdb[:-1]) + "\n")
    data = tmp_path / "data"
    assert run(data, src) == 1
    receipt = json.loads((data / hi.HYDRO_DIR / "ingest_sites_receipt.json").read_text())
    assert receipt["last_status"] == "FAIL" and "USGS services disagree" in receipt["last_error"]


def test_a_truncated_usgs_feed_stops_the_run(tmp_path):
    assert ingest.main(["--src-dir", str(FIXTURES), "--data-dir", str(tmp_path), "--now", "2026-11-15T02:00:00Z"]) == 1


def test_an_empty_response_stops_the_run(tmp_path):
    # CONSTRUCTED: WQP answers with nothing.
    src = tmp_path / "src"
    shutil.copytree(FIXTURES, src)
    (src / "wqp_wells.csv").write_text("")
    assert run(tmp_path / "data", src) == 1
