"""Source-native hydro parsers: candidate observations only, never canonical identity.

Parser gates distinguish complete header recognition from a guessed spreadsheet
column. Neither LUMA PDF text nor an EIA aggregate proves unit-level facts.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

MAX_MEMBER_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1500
MAX_EXPANDED_BYTES = 250 * 1024 * 1024
MAX_EXPANSION_RATIO = 200


@dataclass(frozen=True)
class SourceRow:
    source: str
    row_number: int
    raw: dict[str, str]
    observation: dict[str, Any]
    state: str = "CANDIDATE_NOT_IDENTITY"


def _header_index(header: list[str], required: dict[str, tuple[str, ...]]) -> dict[str, int]:
    normalized = [re.sub(r"\s+", " ", value.strip().casefold()) for value in header]
    if len(normalized) != len(set(normalized)):
        raise ValueError("Duplicate normalized source column")
    mapping: dict[str, int] = {}
    for key, aliases in required.items():
        hits = [i for i, col in enumerate(normalized) if col in aliases]
        if len(hits) != 1:
            raise ValueError(f"Missing or ambiguous source column: {key}")
        mapping[key] = hits[0]
    return mapping


def parse_eia_facility_fuel_csv(raw: bytes) -> list[SourceRow]:
    """Parse exact published plant/prime-mover rows without plant-total synthesis."""
    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None)
    if not header:
        raise ValueError("Empty EIA CSV")
    cols = _header_index(header, {
        "state": ("state",),
        "plant": ("plantcode", "plant code"),
        "period": ("period",),
        "prime_mover": ("primemover", "prime mover"),
        "generation": ("generation",),
    })
    out: list[SourceRow] = []
    for line, values in enumerate(reader, 2):
        if not values or all(not value.strip() for value in values):
            continue
        if len(values) != len(header):
            raise ValueError(f"Line {line}: column count mismatch")
        record = dict(zip(header, values, strict=True))
        if values[cols["state"]].strip().upper() != "PR":
            continue
        plant = values[cols["plant"]].strip()
        period = values[cols["period"]].strip()
        mover = values[cols["prime_mover"]].strip()
        value = values[cols["generation"]].strip()
        if not plant or not re.fullmatch(r"\d+", plant):
            raise ValueError(f"Line {line}: invalid native plant ID")
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            raise ValueError(f"Line {line}: invalid period")
        if not mover or not value:
            state = "UNRESOLVED_MISSING_SOURCE_VALUE"
        else:
            # No conversion to numeric yet: RAW retains precision and published codes.
            state = "CANDIDATE_NOT_IDENTITY"
        out.append(SourceRow(
            source="EIA_FACILITY_FUEL_API", row_number=line, raw=record,
            observation={"plant_code_raw": plant, "period_raw": period,
                         "prime_mover_raw": mover, "generation_raw": value}, state=state,
        ))
    return out


def inspect_eia_923_zip(raw: bytes) -> list[dict[str, Any]]:
    """Inventory members and guard against zip bombs/path collisions.

    No claims about actual plant MWh are emitted until the specific sheet schema
    is inspected and mapped independently.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("Not a valid EIA ZIP") from exc
    with archive:
        infos = [member for member in archive.infolist() if not member.is_dir()]
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            raise ValueError("Excess archive members")
        total = 0
        paths = set()
        result = []
        for info in infos:
            path = PurePosixPath(info.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("Unsafe archive member path")
            if info.filename.casefold() in paths:
                raise ValueError("Duplicate casefolded archive path")
            paths.add(info.filename.casefold())
            if info.flag_bits & 1:
                raise ValueError("Encrypted archive member")
            if info.file_size > MAX_MEMBER_BYTES:
                raise ValueError("Oversized archive member")
            if info.file_size > MAX_EXPANSION_RATIO * max(info.compress_size, 1):
                raise ValueError("Suspicious archive expansion ratio")
            total += info.file_size
            if total > MAX_EXPANDED_BYTES:
                raise ValueError("Excessive archive payload")
            member_hash = hashlib.sha256()
            extracted_bytes = 0
            with archive.open(info) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    extracted_bytes += len(block)
                    if extracted_bytes > MAX_MEMBER_BYTES or extracted_bytes > info.file_size:
                        raise ValueError("Archive member exceeded declared size")
                    member_hash.update(block)
            if extracted_bytes != info.file_size:
                raise ValueError("Archive member size mismatch")
            result.append({"path_raw": info.filename, "uncompressed_bytes": info.file_size,
                           "compressed_bytes": info.compress_size,
                           "member_sha256": member_hash.hexdigest(),
                           "state": "STRUCTURAL_ONLY_NOT_PARSED"})
        return result


def inspect_eia_860m_xlsx(raw: bytes) -> dict[str, Any]:
    """Require a valid OOXML workbook; record sheet names without fabricating rows."""
    if not raw.startswith(b"PK"):
        raise ValueError("Not an XLSX container")
    inspect_eia_923_zip(raw)  # structural ZIP limits before decompression
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("XLSX parser dependency unavailable") from exc
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError("Unparseable XLSX") from exc
    try:
        sheets = list(workbook.sheetnames)
    finally:
        workbook.close()
    if not sheets:
        raise ValueError("Workbook has no sheets")
    return {"sheets": sheets, "state": "SCHEMA_DISCOVERY_ONLY_NOT_CANONICAL",
            "source": "EIA_860M"}


def inspect_luma_pdf(raw: bytes, *, cms_slug_date: str | None = None,
                     pdf_filename_date: str | None = None,
                     internal_report_date: str | None = None) -> dict[str, Any]:
    if not raw.startswith(b"%PDF-") or len(raw) < 8:
        raise ValueError("Invalid PDF signature")
    observed = [date for date in (cms_slug_date, pdf_filename_date, internal_report_date) if date]
    if any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) for date in observed):
        raise ValueError("Invalid published date metadata")
    if not internal_report_date:
        state = "INTERNAL_DATE_UNVERIFIED"
    elif len(set(observed)) > 1:
        state = "TEMPORAL_CONTRADICTION_REVIEW"
    else:
        state = "VISUAL_UNIT_TABLE_REVIEW"
    return {"source": "LUMA_DAILY_AVAILABILITY", "cms_slug_date": cms_slug_date,
            "pdf_filename_date": pdf_filename_date,
            "internal_report_date": internal_report_date,
            "state": state, "unit_status": None, "available_mw": None}

def parse_eia_860m_generator_rows(raw: bytes, *, sheet_name: str,
                                  header_row: int) -> list[SourceRow]:
    """Parse a reviewed generator sheet; caller supplies exact header row.

    The source sheet/row and RAW values remain intact; no name-based crosswalk.
    An unrecognized schema fails rather than inferring a column position.
    """
    if header_row < 1:
        raise ValueError("header_row must be positive")
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("XLSX parser dependency unavailable") from exc
    inspect_eia_923_zip(raw)  # enforce ZIP/member limits before opening workbook
    workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError("Named authoritative sheet absent")
        sheet = workbook[sheet_name]
        iterator = sheet.iter_rows(values_only=True)
        header = None
        for index, values in enumerate(iterator, 1):
            if index == header_row:
                header = [str(v).strip() if v is not None else "" for v in values]
                break
        if header is None:
            raise ValueError("Header row outside sheet")
        mapping = _header_index(header, {
            "plant": ("plant code", "plant id", "plant code (eia)"),
            "generator": ("generator id", "generator id (eia)", "generator code"),
            "state": ("state",),
        })
        rows = []
        for source_line, values in enumerate(iterator, header_row + 1):
            if all(value is None or str(value).strip() == "" for value in values):
                continue
            if len(values) > len(header) and any(
                value is not None and str(value).strip() for value in values[len(header):]
            ):
                raise ValueError("Extra populated columns beyond header")
            cells = list(values[:len(header)])
            cells.extend([None] * (len(header) - len(cells)))
            state = str(cells[mapping["state"]] or "").strip().upper()
            if state != "PR":
                continue
            plant = str(cells[mapping["plant"]] or "").strip()
            generator = str(cells[mapping["generator"]] or "").strip()
            if not plant or not generator:
                raise ValueError(f"Missing source-native ID on row {source_line}")
            raw_row = {h: "" if v is None else str(v) for h, v in zip(header, cells, strict=True)}
            rows.append(SourceRow(
                source="EIA_860M", row_number=source_line,
                raw=raw_row,
                observation={"plant_code_raw": plant, "generator_id_raw": generator,
                             "sheet_name": sheet_name},
            ))
        return rows
    finally:
        workbook.close()



def parse_eia_923_generation_workbook(
    raw: bytes, *, sheet_name: str, header_row: int,
    columns: dict[str, str], source_member_sha256: str,
) -> list[SourceRow]:
    """Extract EIA-923 candidates only under an explicitly reviewed sheet schema.

    The caller supplies literal source-native column headings for state, plant,
    prime mover and the selected net-generation period. The original member hash,
    sheet and physical row are retained; no canonical plant/MWh claims are made.
    """
    if header_row < 1 or set(columns) != {"state", "plant", "prime_mover", "net_generation"}:
        raise ValueError("Incomplete explicit EIA-923 column contract")
    if (len(source_member_sha256) != 64 or
            any(c not in "0123456789abcdef" for c in source_member_sha256)):
        raise ValueError("Invalid source member SHA256")
    if hashlib.sha256(raw).hexdigest() != source_member_sha256:
        raise ValueError("EIA-923 workbook does not match declared member SHA256")
    inspect_eia_923_zip(raw)
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("XLSX parser dependency unavailable") from exc
    book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        if sheet_name not in book.sheetnames:
            raise ValueError("EIA-923 source sheet not present")
        iterator = book[sheet_name].iter_rows(values_only=True)
        header = None
        for number, cells in enumerate(iterator, 1):
            if number == header_row:
                header = ["" if value is None else str(value) for value in cells]
                break
        if header is None:
            raise ValueError("EIA-923 reviewed header row not present")
        positions = _header_index(
            header, {role: (heading.strip().casefold(),) for role, heading in columns.items()}
        )
        if len(set(positions.values())) != len(columns):
            raise ValueError("Distinct EIA-923 roles cannot share a source column")
        observations = []
        for physical_row, values in enumerate(iterator, header_row + 1):
            if all(value is None or str(value).strip() == "" for value in values):
                continue
            if len(values) > len(header) and any(
                value is not None and str(value).strip() for value in values[len(header):]
            ):
                raise ValueError("Unmapped populated EIA-923 source column")
            row = list(values[:len(header)])
            row.extend([None] * (len(header) - len(row)))
            if str(row[positions["state"]] or "").strip().upper() != "PR":
                continue
            plant_value = row[positions["plant"]]
            mover_value = row[positions["prime_mover"]]
            generation_value = row[positions["net_generation"]]
            plant_id = "" if plant_value is None else str(plant_value).strip()
            mover = "" if mover_value is None else str(mover_value).strip()
            if not re.fullmatch(r"\d+", plant_id) or not mover:
                raise ValueError(f"Invalid EIA-923 native ID at row {physical_row}")
            raw_row = {name: "" if value is None else str(value)
                       for name, value in zip(header, row, strict=True)}
            generation = None if generation_value is None else str(generation_value)
            observations.append(SourceRow(
                source="EIA_923_WORKBOOK", row_number=physical_row, raw=raw_row,
                observation={"plant_id_raw": plant_id,
                             "prime_mover_raw": mover,
                             "net_generation_raw": generation,
                             "member_sha256": source_member_sha256,
                             "sheet_name": sheet_name,
                             "generation_header_raw": columns["net_generation"]},
                state=("UNRESOLVED_MISSING_SOURCE_VALUE" if generation is None
                       or not generation.strip() else "CANDIDATE_NOT_IDENTITY"),
            ))
        return observations
    finally:
        book.close()
