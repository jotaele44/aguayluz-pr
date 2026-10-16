import csv
import zipfile
from pathlib import Path

from scripts.acquire_salud_sdwis_water_sources import (
    SDWIS_MEMBER_BASENAME,
    _archive_inventory,
    sha256_file,
)


def test_archive_inventory_enumerates_every_member_and_freezes_selected_bytes(tmp_path):
    archive_path = tmp_path / "sdwa.zip"
    member_rows = [
        ["SUBMISSIONYEARQUARTER", "PWSID", "VIOLATION_ID"],
        ["2026Q3", "PR0000001", "V-1"],
    ]
    member_path = tmp_path / SDWIS_MEMBER_BASENAME
    with member_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(member_rows)

    expected_bytes = member_path.read_bytes()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", "fixture")
        archive.writestr(f"nested/{SDWIS_MEMBER_BASENAME}", expected_bytes)
        archive.writestr("SDWA_REF_CODE_VALUES.csv", "VALUE_TYPE,VALUE_CODE\n")

    extracted = tmp_path / "out" / SDWIS_MEMBER_BASENAME
    inventory, selected = _archive_inventory(
        archive_path,
        extracted_member_path=extracted,
    )

    assert [row["filename"] for row in inventory] == [
        "nested/SDWA_VIOLATIONS_ENFORCEMENT.csv",
        "README.txt",
        "SDWA_REF_CODE_VALUES.csv",
    ]
    assert selected["archive_member"] == "nested/SDWA_VIOLATIONS_ENFORCEMENT.csv"
    assert selected["member_byte_length"] == len(expected_bytes)
    assert selected["member_sha256"] == sha256_file(member_path)
    assert extracted.read_bytes() == expected_bytes


def test_archive_inventory_fails_closed_when_target_member_is_missing(tmp_path):
    archive_path = tmp_path / "sdwa.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("README.txt", "fixture")

    try:
        _archive_inventory(
            archive_path,
            extracted_member_path=tmp_path / SDWIS_MEMBER_BASENAME,
        )
    except ValueError as exc:
        assert "expected exactly one" in str(exc)
    else:
        raise AssertionError("missing SDWIS member must fail closed")
