"""Persisted real producer package through the actual Aguayluz read path."""

import copy

import pytest

from aguayluz.ionosphere_snapshot import snapshot_context
from aguayluz.ionosphere_transport import ROOT, consume_glotec_package, load_reference_coverage


def test_real_persisted_package_is_idempotent_and_lossless():
    raw = (ROOT / "pitirre_glotec_context.package.json").read_bytes()
    schema = (ROOT / "pitirre_observation.v2.schema.json").read_bytes()
    snapshot = snapshot_context()
    result = consume_glotec_package(raw, schema, snapshot)
    assert result == consume_glotec_package(raw, schema, snapshot)
    assert result["record_count"] == 6
    assert all(
        row["producer_envelope"]["payload"]["raw_feature"] == row["raw_feature"]
        for row in snapshot["rows"]
    )
    assert [row["producer_envelope"] for row in snapshot["rows"]] == result["records"]
    assert result["persisted"] is True
    assert result["operational_use_allowed"] is False
    assert (ROOT / "pitirre_glotec_context.package.json").read_bytes() == raw


def test_corruption_and_wrong_source_selection_rejected():
    raw = (ROOT / "pitirre_glotec_context.package.json").read_bytes()
    schema = (ROOT / "pitirre_observation.v2.schema.json").read_bytes()
    snapshot = snapshot_context()
    with pytest.raises(ValueError, match="digest"):
        consume_glotec_package(raw + b" ", schema, snapshot)
    with pytest.raises(ValueError, match="digest"):
        consume_glotec_package(raw, schema + b" ", snapshot)
    altered = copy.deepcopy(snapshot)
    altered["rows"][0]["raw_feature"]["properties"]["tec"] = -1
    with pytest.raises(ValueError, match="whole source row"):
        consume_glotec_package(raw, schema, altered)
    altered = copy.deepcopy(snapshot)
    altered["selected_count"] += 1
    with pytest.raises(ValueError, match="conservation"):
        consume_glotec_package(raw, schema, altered)


def test_frozen_reference_coverage_conserves_every_source_id():
    value = load_reference_coverage()
    assert value["state"] == "PASS_REFERENCE_ENVELOPE_COVERAGE"
    assert value["reference_count"] == value["classified_count"] == 78
    assert value["excluded_count"] == 0
    ids = [r["source_properties"]["geoid"] for r in value["rows"]]
    assert len(ids) == len(set(ids)) == 78
    assert all(r["valid"] and r["source_node_envelope"] == "FULLY_WITHIN" for r in value["rows"])
    assert all(not r["has_z"] and not r["has_m"] for r in value["rows"])


def test_simulated_frozen_bundle_loads_exact_sources_without_network(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(ROOT, tmp_path / "data-sources/ionosphere")
    (tmp_path / "data/geo").mkdir(parents=True)
    shutil.copy2(
        repo / "data/geo/pr_municipios.geojson", tmp_path / "data/geo/pr_municipios.geojson"
    )
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}
    code = 'import sys; sys._MEIPASS=sys.argv[1]; from aguayluz.ionosphere_snapshot import snapshot_context, ARCHIVE; from aguayluz.ionosphere_transport import load_reference_coverage; assert str(ARCHIVE).startswith(sys.argv[1]); v=snapshot_context(); print(v["producer_transport"]["state"], load_reference_coverage()["classified_count"])'
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "PASS_FROZEN_TRANSPORT 78"
