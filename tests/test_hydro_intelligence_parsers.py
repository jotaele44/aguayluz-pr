"""Hydro parser fail-closed positive and negative regression fixtures."""
import hashlib
import io
import zipfile

import pytest

from aguayluz.hydro_intelligence.parsers import (
    inspect_eia_860m_xlsx,
    inspect_eia_923_zip,
    inspect_luma_pdf,
    parse_eia_facility_fuel_csv,
    parse_eia_860m_generator_rows,
    parse_eia_923_generation_workbook,
)


def _zip(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, value in members:
            z.writestr(name, value)
    return out.getvalue()


def test_eia_plant_level_raw_preserved_without_name_binding():
    csv = (
        "state,plantCode,period,primeMover,generation,plantName\n"
        "PR,61225,2026-06,HY,001.250,Caonillas\n"
        "NY,12,2026-06,HY,4,Other\n"
    ).encode()
    rows = parse_eia_facility_fuel_csv(csv)
    assert len(rows) == 1
    assert rows[0].row_number == 2
    assert rows[0].observation["generation_raw"] == "001.250"
    assert rows[0].state == "CANDIDATE_NOT_IDENTITY"


@pytest.mark.parametrize("payload", [
    b"state,plantCode,period,primeMover,generation,generation\nPR,61225,2026-06,HY,1,2\n",
    b"state,plantCode,period,primeMover,generation\nPR,61225,2026-06,HY\n",
    b"state,plantCode,period,primeMover,generation\nPR,NOT_ID,2026-06,HY,1\n",
])
def test_eia_rejects_ambiguous_or_invalid_rows(payload):
    with pytest.raises(ValueError):
        parse_eia_facility_fuel_csv(payload)


def test_zip_members_are_structural_not_measured():
    result = inspect_eia_923_zip(_zip([("file.xlsx", b"sample")]))
    assert len(result) == 1
    assert result[0]["state"] == "STRUCTURAL_ONLY_NOT_PARSED"
    assert result[0]["member_sha256"] == hashlib.sha256(b"sample").hexdigest()


def test_zip_traversal_rejected():
    with pytest.raises(ValueError, match="Unsafe"):
        inspect_eia_923_zip(_zip([("../outside.xlsx", b"x")]))


def test_zip_duplicate_case_insensitive_path_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        inspect_eia_923_zip(_zip([("TABLE.xlsx", b"a"), ("table.xlsx", b"b")]))


def test_luma_conflicting_dates_never_promote_units():
    result = inspect_luma_pdf(b"%PDF-1.7\n", pdf_filename_date="2026-08-30",
                              internal_report_date="2026-08-29")
    assert result["state"] == "TEMPORAL_CONTRADICTION_REVIEW"
    assert result["available_mw"] is None and result["unit_status"] is None


def test_luma_unverified_internal_date_blocks_status():
    assert inspect_luma_pdf(b"%PDF-1.7\n")["state"] == "INTERNAL_DATE_UNVERIFIED"


def test_luma_bad_pdf_and_date_rejected():
    with pytest.raises(ValueError):
        inspect_luma_pdf(b"<html>not pdf</html>")
    with pytest.raises(ValueError):
        inspect_luma_pdf(b"%PDF-1.7\n", internal_report_date="8/29/2026")


def test_eia_workbook_requires_xlsx():
    with pytest.raises(ValueError):
        inspect_eia_860m_xlsx(b"bad")

def test_eia_860m_generator_id_preserved_when_schema_explicit():
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Operating"
    sheet.append(["Preamble", None, None, None])
    sheet.append(["State", "Plant Code", "Generator ID", "Nameplate Capacity (MW)"])
    sheet.append(["PR", 61225, "01", 9.0])
    sheet.append(["NY", 101, "02", 4.0])
    blob = io.BytesIO()
    book.save(blob)
    rows = parse_eia_860m_generator_rows(blob.getvalue(), sheet_name="Operating", header_row=2)
    assert len(rows) == 1
    assert rows[0].row_number == 3
    assert rows[0].observation["plant_code_raw"] == "61225"
    assert rows[0].observation["generator_id_raw"] == "01"
    assert rows[0].state == "CANDIDATE_NOT_IDENTITY"


def test_eia_860m_rejects_unreviewed_sheet_or_header():
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.append(["State", "Plant Code"])
    blob = io.BytesIO()
    book.save(blob)
    with pytest.raises(ValueError):
        parse_eia_860m_generator_rows(blob.getvalue(), sheet_name="Missing", header_row=1)
    with pytest.raises(ValueError):
        parse_eia_860m_generator_rows(blob.getvalue(), sheet_name="Sheet", header_row=1)


def _eia_923_fake_workbook():
    book = pytest.importorskip("openpyxl").Workbook()
    sheet = book.active
    sheet.title = "Reviewed source sheet"
    sheet.append(["Official preamble", None, None, None])
    sheet.append(["State", "Plant Id", "Reported Prime Mover", "Netgen January"])
    sheet.append(["PR", 61225, "HY", 0])
    sheet.append(["PR", 61226, "HY", None])
    sheet.append(["NY", 999, "HY", 42])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_eia923_explicit_header_preserves_zero_and_missing_values():
    raw = _eia_923_fake_workbook()
    expected_sha = hashlib.sha256(raw).hexdigest()
    rows = parse_eia_923_generation_workbook(
        raw, sheet_name="Reviewed source sheet", header_row=2,
        columns={"state": "State", "plant": "Plant Id",
                 "prime_mover": "Reported Prime Mover",
                 "net_generation": "Netgen January"},
        source_member_sha256=expected_sha,
    )
    assert len(rows) == 2
    assert rows[0].row_number == 3
    assert rows[0].observation["net_generation_raw"] == "0"
    assert rows[0].state == "CANDIDATE_NOT_IDENTITY"
    assert rows[1].row_number == 4
    assert rows[1].observation["net_generation_raw"] is None
    assert rows[1].state == "UNRESOLVED_MISSING_SOURCE_VALUE"
    assert rows[0].observation["member_sha256"] == expected_sha


def test_eia923_rejects_unreviewed_schema():
    raw = _eia_923_fake_workbook()
    with pytest.raises(ValueError, match="Missing or ambiguous"):
        parse_eia_923_generation_workbook(
            raw, sheet_name="Reviewed source sheet", header_row=2,
            columns={"state": "State", "plant": "Plant Id",
                     "prime_mover": "Reported Prime Mover",
                     "net_generation": "Invented monthly column"},
            source_member_sha256=hashlib.sha256(raw).hexdigest(),
        )


def test_eia923_rejects_member_hash_mismatch():
    raw = _eia_923_fake_workbook()
    with pytest.raises(ValueError, match="member SHA256"):
        parse_eia_923_generation_workbook(
            raw, sheet_name="Reviewed source sheet", header_row=2,
            columns={"state": "State", "plant": "Plant Id",
                     "prime_mover": "Reported Prime Mover",
                     "net_generation": "Netgen January"},
            source_member_sha256="0" * 64,
        )
