"""The `source_monitors` export stream (thehub-pr ADR 0013).

One row per source in this repo's three source registries, with when the source
last succeeded and how that is known: the committed hydromet run receipts
(RUN_RECEIPT), the latest retrieval in the committed hydromet manifestations
(OUTPUT_DERIVED), or neither (NOT_RECORDED, null time).
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import federation_export as fe  # noqa: E402
import prii_export_utils  # noqa: E402

NOW = "2026-11-11T16:00:00Z"


def _hydromet_sources() -> list[dict]:
    return json.loads((REPO / "config/hydromet_sources.v1.json").read_text())["sources"]


def _registry_ids() -> list[str]:
    hydro = [s["source_id"] for s in json.loads((REPO / "config/hydromet_sources.v1.json").read_text())["sources"]]
    families = []
    for name in ("hazard_advisory_sources.v1.json", "environmental_exposure_sources.v1.json"):
        families += [f["family"] for f in json.loads((REPO / "config" / name).read_text())["families"]]
    return hydro + families


def test_one_row_per_registered_source_on_committed_data():
    rows = fe.build_source_monitors(NOW, data_root=REPO / "data")
    assert sorted(r["source_ref"] for r in rows) == sorted(_registry_ids())
    assert len({r["monitor_id"] for r in rows}) == len(rows)
    by_ref = {r["source_ref"]: r for r in rows}
    for sid in ("nwps_gauges", "stage_iv_pr"):
        assert by_ref[sid]["last_success_basis"] in {"RUN_RECEIPT", "OUTPUT_DERIVED"}
        assert by_ref[sid]["last_success_at"]
        assert by_ref[sid]["registry_path"] == "config/hydromet_sources.v1.json"
    # Hazard-advisory and exposure families have no run receipt and no manifestation to read.
    hydro_ids = {s["source_id"] for s in _hydromet_sources()}
    others = [r for r in rows if r["source_ref"] not in hydro_ids]
    assert others and all(r["last_success_basis"] == "NOT_RECORDED" and r["last_success_at"] is None for r in others)
    # A hydromet source is recorded exactly as far as the committed receipts say, whichever
    # of them have run so far (the refresh bot adds a receipt when a source first succeeds).
    receipts = json.loads((REPO / "data" / fe.HYDROMET_RECEIPTS).read_text())["sources"]
    for sid in sorted(hydro_ids):
        row = by_ref[sid]
        receipt_at = (receipts.get(sid) or {}).get("last_success_utc")
        if receipt_at:
            # The more recent of receipt and output wins; a tie goes to the receipt.
            assert row["last_success_basis"] in {"RUN_RECEIPT", "OUTPUT_DERIVED"}, sid
            assert row["last_success_at"], sid
            assert fe._parse_utc(row["last_success_at"]) >= fe._parse_utc(receipt_at), sid
            if row["last_success_basis"] == "RUN_RECEIPT":
                assert row["last_success_at"] == receipt_at, sid
        else:
            # No receipt: only a mapped manifestation can say it succeeded, otherwise nothing is guessed.
            assert row["last_success_basis"] in {"NOT_RECORDED", "OUTPUT_DERIVED"}, sid
            assert (row["last_success_at"] is None) == (row["last_success_basis"] == "NOT_RECORDED"), sid


def test_every_committed_manifestation_system_is_mapped():
    systems = {json.loads(line).get("source_system")
               for line in (REPO / "data/hydromet_manifestations.jsonl").read_text().splitlines() if line.strip()}
    assert systems <= set(fe.HYDROMET_SOURCE_SYSTEMS), systems - set(fe.HYDROMET_SOURCE_SYSTEMS)
    hydro_ids = {s["source_id"] for s in json.loads((REPO / "config/hydromet_sources.v1.json").read_text())["sources"]}
    assert set(fe.HYDROMET_SOURCE_SYSTEMS.values()) <= hydro_ids


def test_hydromet_source_systems_match_the_ingest_scripts():
    # The mapping is pinned by hand; each registered source's refresh_script declares the
    # SOURCE_SYSTEM string its manifestation rows carry. Read it with ast (no import side
    # effects) so a source with no committed rows yet, such as nws_marine_alerts or airnow,
    # is covered too, and so are extra, missing and misattributed entries.
    declared: dict[str, str] = {}
    for src in _hydromet_sources():
        tree = ast.parse((REPO / src["refresh_script"]).read_text(encoding="utf-8"))
        values = [n.value.value for n in tree.body
                  if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                  and isinstance(n.value.value, str)
                  and any(isinstance(t, ast.Name) and t.id == "SOURCE_SYSTEM" for t in n.targets)]
        assert len(values) == 1, f"{src['refresh_script']} must define one module-level SOURCE_SYSTEM string"
        declared[src["source_id"]] = values[0]
    assert len(set(declared.values())) == len(declared), "two sources share a source_system"
    assert fe.HYDROMET_SOURCE_SYSTEMS == {system: sid for sid, system in declared.items()}


def _data(tmp_path: Path, receipts: dict | None, manifestations: list[dict]) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    if receipts is not None:
        (data / fe.HYDROMET_RECEIPTS).write_text(json.dumps({"schema_version": "aguayluz.hydromet-receipts/v1",
                                                              "sources": receipts}))
    (data / fe.HYDROMET_MANIFESTATIONS).write_text("".join(json.dumps(m) + "\n" for m in manifestations))
    return data


def _hydro(rows):
    return {r["source_ref"]: r for r in rows if r["source_ref"] in {"nwps_gauges", "stage_iv_pr"}}


def test_the_more_recent_of_receipt_and_output_wins(tmp_path):
    data = _data(tmp_path, {
        "nwps_gauges": {"last_attempt_utc": "2026-11-09T10:00:00Z", "last_status": "FAIL",
                        "last_success_utc": "2026-11-08T10:00:00Z"},
    }, [
        {"source_system": "NWPS API v1", "retrieved_at_utc": "2026-11-07T10:00:00Z"},
        {"source_system": "NWPS Stage IV downloads (PR GeoTIFF)", "retrieved_at_utc": "2026-11-09T07:00:00Z"},
        {"source_system": "Some future system", "retrieved_at_utc": "2026-11-10T00:00:00Z"},
    ])
    hydro = _hydro(fe.build_source_monitors(NOW, data_root=data))
    nwps, stage = hydro["nwps_gauges"], hydro["stage_iv_pr"]
    # A failed latest attempt keeps the last success, and the receipt is newer than the output.
    assert (nwps["last_success_at"], nwps["last_success_basis"]) == ("2026-11-08T10:00:00Z", "RUN_RECEIPT")
    assert (nwps["last_attempt_at"], nwps["last_attempt_status"]) == ("2026-11-09T10:00:00Z", "failure")
    # No receipt: the latest retrieval in the manifestations.
    assert (stage["last_success_at"], stage["last_success_basis"]) == ("2026-11-09T07:00:00Z", "OUTPUT_DERIVED")
    assert stage["last_attempt_at"] is None


def test_without_receipts_or_manifestations_nothing_is_guessed(tmp_path):
    hydro = _hydro(fe.build_source_monitors(NOW, data_root=_data(tmp_path, None, [])))
    assert all(r["last_success_basis"] == "NOT_RECORDED" and r["last_success_at"] is None for r in hydro.values())


def test_vocabulary_mapping():
    assert fe._cadence_from_seconds(900) == "realtime"
    assert fe._cadence_from_seconds(86400) == "daily"
    assert fe._cadence_from_text("weekly; historical records may be revised") == "weekly"
    assert fe._cadence_from_text("periodic sampling notifications") == "unknown"
    assert fe._binding_status("BOUND") == "active"
    assert fe._binding_status("BOUND_PR_SITE_DENOMINATOR_OPEN") == "partial"
    assert fe._binding_status("OPEN_PR_DENOMINATOR") == "not_active"
    assert fe._monitor_window("daily", "not a number") == 86400


def test_package_lists_the_stream_and_its_manifest_validates(tmp_path):
    rows = fe.build_source_monitors(NOW, data_root=REPO / "data")
    manifest_path = fe.write_package({"source_monitors": rows}, tmp_path / "pkg", "test", NOW)
    manifest = json.loads(manifest_path.read_text())
    assert [f["stream"] for f in manifest["files"]] == ["source_monitors"]
    assert manifest["files"][0]["schema_id"] == "federation_source_monitor.schema.json"
    assert manifest["files"][0]["record_count"] == len(rows)
    schema = json.loads((REPO / "schemas/federation_export_manifest.schema.json").read_text())
    jsonschema.validate(manifest, schema)


def test_local_helpers_keep_their_ids_and_reach_the_pinned_package():
    # scripts/prii_export_utils.py shadows the pinned package; its own helpers stay
    # as they were (ids depend on them) and other names come from the package.
    assert Path(prii_export_utils.__file__).resolve() == REPO / "scripts" / "prii_export_utils.py"
    import hashlib
    assert prii_export_utils.fid("ent", "a", None) == "ent_" + hashlib.sha256(b"a|").hexdigest()[:32]
    assert prii_export_utils.norm("Río Grande") == "rio_grande"
    assert callable(prii_export_utils.source_monitor_row)
    assert callable(prii_export_utils.resolve_last_success)
    with pytest.raises(AttributeError):
        prii_export_utils.no_such_helper  # noqa: B018


def test_pinned_package_loads_from_an_archive(tmp_path):
    # The desktop build bundles the pinned package in PyInstaller's archive, where it has
    # no source file on disk, so the shim must import it with the loader its finder
    # returns. A zip on sys.path is the same case: an archive-backed loader, no file to reopen.
    import subprocess
    import zipfile

    package = Path(prii_export_utils._pinned_package().__file__).parent
    archive = tmp_path / "pinned.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in sorted(package.glob("*.py")):
            zf.write(path, f"prii_export_utils/{path.name}")
    code = "\n".join([
        "import sys",
        "from pathlib import Path",
        f"sys.path[:0] = [{str(REPO / 'scripts')!r}, {str(archive)!r}]",
        "import prii_export_utils as shim",
        f"assert Path(shim.__file__).resolve() == Path({str(REPO / 'scripts' / 'prii_export_utils.py')!r})",
        "assert shim.norm('Río Grande') == 'rio_grande'",
        "row = shim.source_monitor_row",
        "assert callable(row) and row.__module__ == 'prii_export_utils.source_monitor', row.__module__",
        "assert sys.modules['prii_export_utils'] is shim",
    ])
    # -S: no site-packages, so the zip is the only place the pinned package can come from.
    result = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
