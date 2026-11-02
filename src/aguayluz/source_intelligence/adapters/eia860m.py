"""EIA-860M source adapter with fail-closed XLSX parsing."""
from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal, InvalidOperation
from typing import Any

from .base import AdapterCapabilities, RawArtifact

SOURCE_FAMILY_ID = "EIA_860M"
INDEX_URL = "https://www.eia.gov/electricity/data/eia860m/"
MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

HEADER_ALIASES = {
    "plant_state": {"plant state"},
    "plant_id": {"plant id"},
    "generator_id": {"generator id"},
    "plant_name": {"plant name"},
    "nameplate_mw": {"nameplate capacity mw"},
    "net_summer_mw": {"net summer capacity mw"},
    "net_winter_mw": {"net winter capacity mw"},
    "energy_source_code": {"energy source code"},
    "prime_mover_code": {"prime mover code"},
    "status_code": {"status", "status code"},
    "technology": {"technology"},
}
CORE_REQUIRED_FIELDS = {"plant_state", "plant_id", "generator_id", "nameplate_mw"}


def canonical_month_url(month: str, year: int) -> str:
    value = month.strip().lower()
    if value not in MONTHS:
        raise ValueError(f"unknown month {month!r}")
    if year < 2018:
        raise ValueError("Puerto Rico monthly EIA-860M coverage starts in 2018")
    return (
        "https://www.eia.gov/electricity/data/eia860m/archive/xls/"
        f"{value}_generator{year}.xlsx"
    )


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _column_index(cell_ref: str) -> int:
    letters = "".join(character for character in cell_ref if character.isalpha())
    if not letters:
        raise ValueError(f"cell reference has no column letters: {cell_ref!r}")
    index = 0
    for character in letters.upper():
        index = index * 26 + (ord(character) - ord("A") + 1)
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values = []
    for node in root.findall(f"{{{_MAIN_NS}}}si"):
        values.append(
            "".join(
                text_node.text or ""
                for text_node in node.findall(f".//{{{_MAIN_NS}}}t")
            )
        )
    return values


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(
            node.text or "" for node in cell.findall(f".//{{{_MAIN_NS}}}t")
        )
    value = cell.find(f"{{{_MAIN_NS}}}v")
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        try:
            return shared[int(value.text)]
        except (IndexError, ValueError) as exc:
            raise ValueError("invalid shared-string index") from exc
    return value.text


def _worksheet_rows(archive: zipfile.ZipFile, path: str) -> list[list[str]]:
    shared = _shared_strings(archive)
    root = ET.fromstring(archive.read(path))
    rows: list[list[str]] = []
    for row in root.findall(f".//{{{_MAIN_NS}}}sheetData/{{{_MAIN_NS}}}row"):
        values: list[str] = []
        fallback_index = 0
        for cell in row.findall(f"{{{_MAIN_NS}}}c"):
            ref = cell.attrib.get("r")
            index = _column_index(ref) if ref else fallback_index
            while len(values) <= index:
                values.append("")
            values[index] = _cell_text(cell, shared)
            fallback_index = index + 1
        rows.append(values)
    return rows


def _sheet_paths(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        node.attrib["Id"]: node.attrib["Target"]
        for node in relationships.findall(f"{{{_PKG_REL_NS}}}Relationship")
    }
    result: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        rel_id = sheet.attrib.get(f"{{{_REL_NS}}}id")
        name = sheet.attrib.get("name")
        if not rel_id or not name or rel_id not in rel_targets:
            raise ValueError("workbook sheet relationship is incomplete")
        target = rel_targets[rel_id]
        if target.startswith("/"):
            normalized = target.lstrip("/")
        elif target.startswith("xl/"):
            normalized = target
        else:
            normalized = posixpath.normpath(posixpath.join("xl", target))
        if not normalized.startswith("xl/") or ".." in normalized.split("/"):
            raise ValueError("workbook sheet target escapes xl/")
        if normalized not in archive.namelist():
            raise ValueError(f"workbook sheet target is missing: {normalized}")
        result[name] = normalized
    if not result:
        raise ValueError("workbook contains no sheets")
    return result


def _find_sheet(sheet_paths: dict[str, str], prefix: str) -> tuple[str, str]:
    matches = [
        (name, path)
        for name, path in sheet_paths.items()
        if _normalize_header(name).startswith(prefix)
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {prefix!r} sheet, found {len(matches)}")
    return matches[0]


def detect_header(
    rows: list[list[str]],
    *,
    require_status: bool,
    max_scan_rows: int = 50,
) -> tuple[int, dict[str, int], dict[str, str]]:
    for row_index, row in enumerate(rows[:max_scan_rows]):
        normalized = [_normalize_header(value) for value in row]
        mapping: dict[str, int] = {}
        raw_headers: dict[str, str] = {}
        for field, aliases in HEADER_ALIASES.items():
            for index, value in enumerate(normalized):
                if value in aliases:
                    mapping[field] = index
                    raw_headers[field] = row[index]
                    break
        required = set(CORE_REQUIRED_FIELDS)
        if require_status:
            required.add("status_code")
        if required <= set(mapping) and (
            "energy_source_code" in mapping or "technology" in mapping
        ):
            return row_index, mapping, raw_headers
    raise ValueError("required EIA-860M header row was not found in preamble scan")


def _optional(row: list[str], mapping: dict[str, int], field: str) -> str:
    index = mapping.get(field)
    return row[index] if index is not None and index < len(row) else ""


def _decimal(value: str, *, field: str, required: bool) -> float | None:
    text = value.strip().replace(",", "")
    if not text:
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field} is not numeric: {value!r}") from exc
    if number < 0:
        raise ValueError(f"{field} cannot be negative")
    return float(number)


def _status_code(value: str, *, retired: bool) -> str:
    text = value.strip()
    if retired and not text:
        return "RE"
    if text.startswith("(") and ")" in text:
        text = text[1 : text.index(")")]
    else:
        text = text.split(maxsplit=1)[0] if text else ""
    if not text:
        raise ValueError("operating EIA-860M row has blank status")
    return text.upper()


def _is_hydro(row: list[str], mapping: dict[str, int]) -> bool:
    energy = _optional(row, mapping, "energy_source_code").strip().upper()
    technology = _optional(row, mapping, "technology").casefold()
    return energy == "WAT" or "hydro" in technology


def _parse_sheet(
    rows: list[list[str]],
    *,
    record_kind: str,
) -> list[dict[str, Any]]:
    retired = record_kind == "RETIRED"
    header_index, mapping, _ = detect_header(rows, require_status=not retired)
    header_row = rows[header_index]
    parsed: list[dict[str, Any]] = []
    for row_offset, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(value != "" for value in row):
            continue
        state_raw = _optional(row, mapping, "plant_state")
        if state_raw.strip().upper() != "PR" or not _is_hydro(row, mapping):
            continue

        plant_id_raw = _optional(row, mapping, "plant_id")
        generator_id_raw = _optional(row, mapping, "generator_id")
        plant_id = plant_id_raw.strip()
        generator_id = generator_id_raw.strip()
        if not plant_id or not generator_id:
            raise ValueError(
                f"Puerto Rico hydro row {row_offset} has null plant/generator identity"
            )

        raw = {
            header_row[index]: row[index] if index < len(row) else ""
            for index in range(len(header_row))
            if header_row[index] != ""
        }
        normalized = {
            "record_kind": record_kind,
            "plant_state": "PR",
            "plant_id": plant_id,
            "generator_id": generator_id,
            "plant_name": _optional(row, mapping, "plant_name").strip(),
            "nameplate_mw": _decimal(
                _optional(row, mapping, "nameplate_mw"),
                field="nameplate_mw",
                required=True,
            ),
            "net_summer_mw": _decimal(
                _optional(row, mapping, "net_summer_mw"),
                field="net_summer_mw",
                required=False,
            ),
            "net_winter_mw": _decimal(
                _optional(row, mapping, "net_winter_mw"),
                field="net_winter_mw",
                required=False,
            ),
            "energy_source_code": _optional(
                row, mapping, "energy_source_code"
            ).strip().upper(),
            "prime_mover_code": _optional(
                row, mapping, "prime_mover_code"
            ).strip().upper(),
            "status_code": _status_code(
                _optional(row, mapping, "status_code"),
                retired=retired,
            ),
            "source_row_number": row_offset,
        }
        parsed.append(
            {
                "raw": raw,
                "normalized": normalized,
                "identity": {
                    "plant_id": plant_id,
                    "generator_id": generator_id,
                    "key": f"{plant_id}::{generator_id}",
                },
            }
        )
    return parsed


def _normalized(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("normalized")
    return value if isinstance(value, dict) else row


def validate_generator_invariants(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("expected nonzero Puerto Rico hydro rows")
    seen: set[tuple[str, str]] = set()
    duplicate_keys: list[str] = []
    for row in rows:
        value = _normalized(row)
        plant_id = str(value.get("plant_id") or "")
        generator_id = str(value.get("generator_id") or "")
        if not plant_id.isdigit():
            raise ValueError(f"EIA Plant ID must be numeric: {plant_id!r}")
        if not generator_id:
            raise ValueError("Generator ID cannot be blank")
        key = (plant_id, generator_id)
        if key in seen:
            duplicate_keys.append(f"{plant_id}::{generator_id}")
        seen.add(key)
        nameplate = value.get("nameplate_mw")
        if not isinstance(nameplate, (int, float)) or nameplate < 0:
            raise ValueError(f"invalid nameplate_mw for {plant_id}::{generator_id}")
    if duplicate_keys:
        raise ValueError(f"duplicate Plant ID + Generator ID keys: {sorted(duplicate_keys)}")
    return {
        "state": "PASS",
        "record_count": len(rows),
        "identity_count": len(seen),
        "duplicate_identity_count": 0,
    }


def compare_identity_snapshots(
    a_rows: list[dict[str, Any]],
    b_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    validate_generator_invariants(a_rows)
    validate_generator_invariants(b_rows)

    def index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
        return {
            (
                str(_normalized(row)["plant_id"]),
                str(_normalized(row)["generator_id"]),
            ): _normalized(row)
            for row in rows
        }

    a = index(a_rows)
    b = index(b_rows)
    a_keys = set(a)
    b_keys = set(b)
    intersection = a_keys & b_keys
    a_only = a_keys - b_keys
    b_only = b_keys - a_keys
    union = a_keys | b_keys
    symmetric_difference = a_keys ^ b_keys
    compare_fields = ("plant_name", "nameplate_mw", "status_code")
    changed = sorted(
        f"{plant_id}::{generator_id}"
        for plant_id, generator_id in intersection
        if any(a[(plant_id, generator_id)].get(field) != b[(plant_id, generator_id)].get(field)
               for field in compare_fields)
    )
    return {
        "intersection": len(intersection),
        "a_only": len(a_only),
        "b_only": len(b_only),
        "union": len(union),
        "symmetric_difference": len(symmetric_difference),
        "changed": len(changed),
        "changed_keys": changed,
        "a_nameplate_mw": round(sum(float(row["nameplate_mw"]) for row in a.values()), 6),
        "b_nameplate_mw": round(sum(float(row["nameplate_mw"]) for row in b.values()), 6),
    }


class EIA860MAdapter:
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id="eia860m",
            artifact_types=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            authentication_class="NONE",
        )

    def discover(self, checkpoint: dict[str, Any] | None = None) -> list[str]:
        checkpoint = checkpoint or {}
        year = int(checkpoint.get("year", 2026))
        months = checkpoint.get("months", MONTHS)
        return [canonical_month_url(str(month), year) for month in months]

    def validate_transport(self, artifact: RawArtifact) -> None:
        if artifact.http_status != 200:
            raise ValueError(f"unexpected HTTP status {artifact.http_status}")
        if "spreadsheetml.sheet" not in artifact.media_type.lower():
            raise ValueError(f"content type is not XLSX: {artifact.media_type}")
        if not artifact.content.startswith(b"PK"):
            raise ValueError("XLSX magic bytes missing")
        try:
            with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile as exc:
            raise ValueError("invalid XLSX ZIP container") from exc
        required = {
            "[Content_Types].xml",
            "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels",
        }
        missing = sorted(required - names)
        if missing:
            raise ValueError(f"XLSX missing required members: {missing}")

    def _schema_descriptor(self, artifact: RawArtifact) -> dict[str, Any]:
        self.validate_transport(artifact)
        with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
            sheets = _sheet_paths(archive)
            operating_name, operating_path = _find_sheet(sheets, "operating")
            retired_name, retired_path = _find_sheet(sheets, "retired")
            operating_rows = _worksheet_rows(archive, operating_path)
            retired_rows = _worksheet_rows(archive, retired_path)
            operating_header, _, _ = detect_header(
                operating_rows, require_status=True
            )
            retired_header, _, _ = detect_header(
                retired_rows, require_status=False
            )
            return {
                "sheet_names": list(sheets),
                "operating_sheet": operating_name,
                "retired_sheet": retired_name,
                "operating_header": operating_rows[operating_header],
                "retired_header": retired_rows[retired_header],
            }

    def fingerprint_schema(self, artifact: RawArtifact) -> str:
        encoded = json.dumps(
            self._schema_descriptor(artifact),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def parse_pr_hydro(self, artifact: RawArtifact) -> list[dict[str, Any]]:
        self.validate_transport(artifact)
        with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
            sheets = _sheet_paths(archive)
            _, operating_path = _find_sheet(sheets, "operating")
            _, retired_path = _find_sheet(sheets, "retired")
            rows = [
                *_parse_sheet(
                    _worksheet_rows(archive, operating_path),
                    record_kind="OPERATING",
                ),
                *_parse_sheet(
                    _worksheet_rows(archive, retired_path),
                    record_kind="RETIRED",
                ),
            ]
        validate_generator_invariants(rows)
        return rows

    def parse(self, artifact: RawArtifact) -> list[dict[str, Any]]:
        return self.parse_pr_hydro(artifact)
