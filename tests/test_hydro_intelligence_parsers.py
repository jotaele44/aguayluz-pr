"""Hydro parser fail-closed positive and negative regression fixtures."""
import io
import zipfile

import pytest

from aguayluz.hydro_intelligence.parsers import (
    inspect_eia_860m_xlsx,
    inspect_eia_923_zip,
    inspect_luma_pdf,
    parse_eia_facility_fuel_csv,
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
