import importlib.util
import zipfile
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "adjudicate_zip_manifestations.py"
_SPEC = importlib.util.spec_from_file_location("adjudicate_zip_manifestations", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
classify = _MODULE.classify


def _zip(path: Path, members: dict[str, bytes], compression: int) -> None:
    with zipfile.ZipFile(path, "w", compression=compression) as zf:
        for name, payload in members.items():
            zf.writestr(name, payload)


def test_byte_identical(tmp_path: Path):
    a = tmp_path / "a.zip"
    _zip(a, {"x.txt": b"x"}, zipfile.ZIP_DEFLATED)
    b = tmp_path / "b.zip"
    b.write_bytes(a.read_bytes())
    r = classify(a, b)
    assert r["classification"] == "BYTE_IDENTICAL"
    assert r["member_path_identity"] is True
    assert r["payload_multiset_identity"] is True


def test_pure_recompression(tmp_path: Path):
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    members = {"x.txt": b"same", "nested/y.bin": b"payload"}
    _zip(a, members, zipfile.ZIP_STORED)
    _zip(b, members, zipfile.ZIP_DEFLATED)
    r = classify(a, b)
    assert r["old"]["outer_sha256"] != r["new"]["outer_sha256"]
    assert r["classification"] == "PURE_RECOMPRESSION"
    assert r["path_deltas"] == []


def test_same_payloads_different_paths(tmp_path: Path):
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    _zip(a, {"old/x.txt": b"same"}, zipfile.ZIP_STORED)
    _zip(b, {"new/x.txt": b"same"}, zipfile.ZIP_STORED)
    r = classify(a, b)
    assert r["classification"] == "SAME_PAYLOADS_DIFFERENT_PATHS"
    assert r["member_path_identity"] is False
    assert r["payload_multiset_identity"] is True


def test_distinct_payloads(tmp_path: Path):
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    _zip(a, {"x.txt": b"old"}, zipfile.ZIP_STORED)
    _zip(b, {"x.txt": b"new"}, zipfile.ZIP_STORED)
    r = classify(a, b)
    assert r["classification"] == "DISTINCT_PAYLOADS"
    assert r["payload_multiset_identity"] is False
