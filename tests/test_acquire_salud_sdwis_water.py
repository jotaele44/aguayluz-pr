import zipfile

import pytest
from scripts.acquire_salud_sdwis_water import (
    EPA_MEMBER_BASENAME,
    _validate_pdf,
    _validate_zip,
    extract_member,
    locate_member,
    sha256_file,
)


def test_pdf_validation_rejects_non_pdf(tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"<html>not a pdf</html>")

    with pytest.raises(ValueError, match="not a PDF"):
        _validate_pdf(path)


def test_zip_member_selection_is_exact_and_extraction_is_byte_preserving(tmp_path):
    archive_path = tmp_path / "sdwa.zip"
    expected = b"SUBMISSIONYEARQUARTER,PWSID,VIOLATION_ID\n2026Q3,PR0000001,V-1\n"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(f"nested/{EPA_MEMBER_BASENAME}", expected)
        archive.writestr("nested/OTHER.csv", b"x,y\n1,2\n")

    _validate_zip(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        assert locate_member(archive) == f"nested/{EPA_MEMBER_BASENAME}"

    target = tmp_path / EPA_MEMBER_BASENAME
    receipt = extract_member(archive_path, target)

    assert target.read_bytes() == expected
    assert receipt["member_name"] == f"nested/{EPA_MEMBER_BASENAME}"
    assert receipt["member_uncompressed_size"] == len(expected)
    assert receipt["member_sha256"] == sha256_file(target)


def test_member_selection_fails_closed_on_duplicate_basename(tmp_path):
    archive_path = tmp_path / "sdwa.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(f"a/{EPA_MEMBER_BASENAME}", b"a")
        archive.writestr(f"b/{EPA_MEMBER_BASENAME}", b"b")

    with (
        zipfile.ZipFile(archive_path) as archive,
        pytest.raises(ValueError, match="expected exactly one"),
    ):
        locate_member(archive)
