"""Negative and positive guards for independent frozen-source adjudication."""

import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "pfas_scope_gate",
    Path(__file__).resolve().parents[1] / "scripts/verify_frozen_pfas_pr_scope.py",
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def archive(entries, compression=zipfile.ZIP_STORED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as z:
        for name, payload in entries:
            z.writestr(name, payload)
    return stream.getvalue()


def test_all_archive_classes_preserve_payload_and_path_distinctions():
    a = archive([("raw.txt", "x" * 100)])
    assert M.compare_archives(a, a)["classification"] == "BYTE_IDENTICAL"
    recompressed = archive([("raw.txt", "x" * 100)], zipfile.ZIP_DEFLATED)
    assert M.compare_archives(a, recompressed)["classification"] == "PURE_RECOMPRESSION"
    renamed = archive([("moved.txt", "x" * 100)])
    assert M.compare_archives(a, renamed)["classification"] == "SAME_PAYLOADS_DIFFERENT_PATHS"
    changed = archive([("raw.txt", "y" * 100)])
    result = M.compare_archives(a, changed)
    assert result["classification"] == "DISTINCT_PAYLOADS"
    assert result["intersection"] == 0
    assert result["a_only"] == result["b_only"] == 1
    assert result["union"] == result["symmetric_difference"] == 2


def test_duplicate_paths_are_never_collapsed():
    with pytest.warns(UserWarning):
        bad = archive([("raw.txt", "one"), ("raw.txt", "two")])
    with pytest.raises(ValueError, match="duplicate"):
        M.zip_manifest(bad)


def test_raw_tsv_fields_are_preserved_and_schema_defects_fail():
    header, rows = M.table(b"PWSID\tName\nPR0000001\t  raw name  \n")
    assert header == ["PWSID", "Name"]
    assert rows == [("PR0000001", "  raw name  ")]
    for raw in (b"PWSID\tPWSID\nA\tB\n", b"PWSID\tName\nA\tB\textra\n", b"PWSID\tName\nA\n", b""):
        with pytest.raises(ValueError):
            M.table(raw)


def test_unverified_artifact_is_rejected_before_source_parsing():
    with pytest.raises(ValueError, match="bundle differs"):
        M.verify_bundle(b"not the immutable artifact", b"")


def test_selection_rederived_from_source_and_id_state_conflicts_fail():
    raw = b"PWSID\tState\tName\nPR0000001\tPR\tMayag\xfcez  \nPA0000001\tPA\tOther\n"
    header, selected, counts = M.select_pr_source(archive([("UCMR5_All_MA_WY.txt", raw)]))
    assert header == ["PWSID", "State", "Name"]
    assert list(selected) == [("PR0000001", "PR", "Mayag\u00fcez  ")]
    assert counts["source"] == 2 and counts["retained"] == counts["excluded"] == 1
    with pytest.raises(ValueError, match="contradiction"):
        M.select_pr_source(
            archive([("UCMR5_All_MA_WY.txt", raw.replace(b"PR0000001\tPR", b"PR0000001\tPA"))])
        )
