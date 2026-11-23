"""scripts/ingest_hydro_aquifers.py offline, on the real HA 730-N release (pinned bytes).

Needs the [geo] extra; skipped where geopandas is not installed (the CI test job), and run
by anyone rebuilding the polygons. Failure cases are CONSTRUCTED from copies.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("geopandas")

from aguayluz import hydro_inventory as hi  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "hydro_inventory"

_SPEC = importlib.util.spec_from_file_location("ingest_hydro_aquifers", REPO / "scripts" / "ingest_hydro_aquifers.py")
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest
_SPEC.loader.exec_module(ingest)


def prepared(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "geo").mkdir(parents=True)
    shutil.copy(REPO / "data" / "geo" / "pr_municipios.geojson", data / "geo" / "pr_municipios.geojson")
    return data


def run(data, src=FIXTURES, *extra):
    return ingest.main(["--src-dir", str(src), "--data-dir", str(data), "--now", "2026-11-15T02:00:00Z", *extra])


def test_offline_run_passes_the_datum_gate_and_closes_the_polygon_ledger(tmp_path):
    data = prepared(tmp_path)
    assert run(data) == 0
    receipt = json.loads((data / hi.HYDRO_DIR / "ingest_aquifers_receipt.json").read_text())
    checks = receipt["datum"]["checks"]
    assert checks["puerto_rico_1940"]["median_m"] < 100 < checks["declared_nad27"]["median_m"]
    assert abs(checks["declared_nad27"]["median_north_offset_m"]) > 150
    ledger = receipt["ledgers"]["ha730_polygons"]
    assert ledger["source"] == 473 and ledger["delta"] == 0
    assert ledger["excluded_by_reason"]["outside Puerto Rico (U.S. Virgin Islands)"] == 151
    for code, check in receipt["simplification"]["area_check"].items():
        assert abs(check["relative_change"]) <= ingest.AREA_TOLERANCE, code


def test_polygons_and_claims_match_the_committed_files(tmp_path):
    data = prepared(tmp_path)
    assert run(data) == 0
    assert (data / "geo" / "pr_aquifers.geojson").read_bytes() == (REPO / "data" / "geo" / "pr_aquifers.geojson").read_bytes()
    built = {c["source_feature_id"] for c in hi.read_claims(data / hi.HYDRO_DIR / "claims_aquifers.jsonl")
             if c["source_key"] == "usgs_ha730_aquifers_pr"}
    committed = {c["source_feature_id"] for c in hi.read_claims(REPO / "data" / hi.HYDRO_DIR / "claims_aquifers.jsonl")
                 if c["source_key"] == "usgs_ha730_aquifers_pr"}
    assert built == committed and len(built) == 104


def test_a_changed_release_stops_the_run(tmp_path):
    # CONSTRUCTED: one trailing byte on the pinned archive.
    src = tmp_path / "src"
    shutil.copytree(FIXTURES, src)
    (src / "aquifers_pr_shp.zip").write_bytes((src / "aquifers_pr_shp.zip").read_bytes() + b"\n")
    data = prepared(tmp_path)
    assert run(data, src) == 1
    receipt = json.loads((data / hi.HYDRO_DIR / "ingest_aquifers_receipt.json").read_text())
    assert receipt["last_status"] == "FAIL" and "differs from the pin" in receipt["last_error"]


def test_a_quote_that_left_the_source_page_stops_the_run(tmp_path):
    # CONSTRUCTED: the Mona/Culebra sentence removed from the HA 730-N page.
    src = tmp_path / "src"
    shutil.copytree(FIXTURES, src)
    page = src / "ha730_text" / "N-PR_VItext1.html"
    page.write_text(page.read_text(errors="ignore").replace("lack any significant", "are not"))
    assert run(prepared(tmp_path), src) == 1
