import csv
import zipfile
from pathlib import Path

from scripts.freeze_salud_sdwis_2025_sources import (
    TARGET_MEMBER,
    _pwsid_text_inventory,
    filter_pr_year,
    sha256_file,
    zip_inventory,
)


def _write_member(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "SUBMISSIONYEARQUARTER",
        "PWSID",
        "VIOLATION_ID",
        "NON_COMPL_PER_BEGIN_DATE",
        "NON_COMPL_PER_END_DATE",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_zip_inventory_enumerates_all_members_and_freezes_target_bytes(tmp_path):
    source_member = tmp_path / TARGET_MEMBER
    _write_member(
        source_member,
        [
            {
                "SUBMISSIONYEARQUARTER": "2026Q3",
                "PWSID": "PR0000001",
                "VIOLATION_ID": "V-1",
                "NON_COMPL_PER_BEGIN_DATE": "2025-01-01",
                "NON_COMPL_PER_END_DATE": "2025-12-31",
            }
        ],
    )
    expected = source_member.read_bytes()
    archive_path = tmp_path / "sdwa.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", "fixture")
        archive.writestr(f"nested/{TARGET_MEMBER}", expected)
        archive.writestr("SDWA_REF_CODE_VALUES.csv", "VALUE_TYPE,VALUE_CODE\n")

    extracted = tmp_path / "raw" / TARGET_MEMBER
    inventory, member = zip_inventory(archive_path, target_path=extracted)

    assert [row["filename"] for row in inventory] == [
        f"nested/{TARGET_MEMBER}",
        "README.txt",
        "SDWA_REF_CODE_VALUES.csv",
    ]
    assert member["member_name"] == f"nested/{TARGET_MEMBER}"
    assert member["member_byte_length"] == len(expected)
    assert member["member_sha256"] == sha256_file(source_member)
    assert extracted.read_bytes() == expected


def test_filter_pr_year_closes_every_source_row(tmp_path):
    member = tmp_path / TARGET_MEMBER
    _write_member(
        member,
        [
            {
                "SUBMISSIONYEARQUARTER": "2026Q3",
                "PWSID": "PR0000001",
                "VIOLATION_ID": "V-1",
                "NON_COMPL_PER_BEGIN_DATE": "2025-01-01",
                "NON_COMPL_PER_END_DATE": "2025-12-31",
            },
            {
                "SUBMISSIONYEARQUARTER": "2026Q3",
                "PWSID": "NY0000001",
                "VIOLATION_ID": "V-2",
                "NON_COMPL_PER_BEGIN_DATE": "2025-01-01",
                "NON_COMPL_PER_END_DATE": "2025-12-31",
            },
            {
                "SUBMISSIONYEARQUARTER": "2026Q3",
                "PWSID": "PR0000002",
                "VIOLATION_ID": "V-3",
                "NON_COMPL_PER_BEGIN_DATE": "2024-01-01",
                "NON_COMPL_PER_END_DATE": "2024-12-31",
            },
            {
                "SUBMISSIONYEARQUARTER": "2026Q3",
                "PWSID": "PR0000003",
                "VIOLATION_ID": "V-4",
                "NON_COMPL_PER_BEGIN_DATE": "",
                "NON_COMPL_PER_END_DATE": "",
            },
        ],
    )

    receipt, unresolved = filter_pr_year(
        member,
        year=2025,
        output_path=tmp_path / "pr_2025.csv",
    )

    assert receipt["source_arithmetic"] == {
        "source": 4,
        "retained": 1,
        "excluded": 2,
        "excluded_non_pr": 1,
        "excluded_pr_no_year_overlap": 1,
        "unresolved": 1,
        "accounted": 4,
        "delta": 0,
        "state": "PASS",
    }
    assert len(unresolved) == 1
    assert unresolved[0]["reason"] == "NONCOMPLIANCE_PERIOD_MISSING"


def test_pwsid_text_inventory_preserves_page_and_line_signals():
    inventory = _pwsid_text_inventory(
        "Header\nPR0000001 first system\n\f"
        "PR0000002 second system\nPR0000001 repeated\n\f"
    )

    assert inventory["text_page_count"] == 2
    assert inventory["distinct_pwsids"] == ["PR0000001", "PR0000002"]
    assert inventory["pwsid_occurrences"] == 3
    assert inventory["pwsid_signal_lines"][0] == {
        "page": 1,
        "line": 2,
        "pwsids": ["PR0000001"],
        "text": "PR0000001 first system",
    }
