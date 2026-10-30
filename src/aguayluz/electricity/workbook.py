"""Offline-first, bounded OOXML reader. Unknown layouts remain quarantined."""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import datetime
from xml.etree import ElementTree as ET

from aguayluz.electricity.evidence import GeneratorClaim

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
HEADERS = ("Plant ID", "Generator ID", "Plant State", "Plant Name", "Nameplate Capacity (MW)")


def parse_860m(raw: bytes, *, sheet_path: str, receipt_sha256: str, effective_at: datetime) -> dict:
    """Parse an explicitly selected worksheet, never guess names or numeric IDs."""
    if hashlib.sha256(raw).hexdigest() != receipt_sha256:
        raise ValueError("workbook source digest mismatch")
    if not re.fullmatch(r"xl/worksheets/sheet[1-9][0-9]*\.xml", sheet_path):
        raise ValueError("explicit OOXML worksheet path required")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 2000 or len({m.filename for m in members}) != len(members) or sum(m.file_size for m in members) > 100_000_000:
            raise ValueError("workbook size or duplicate-member gate")
        for member in members:
            if member.filename.startswith("/") or ".." in member.filename.split("/") or member.flag_bits & 1:
                raise ValueError("unsafe workbook member")

        def xml(name):
            payload = archive.read(name)
            if b"<!DOCTYPE" in payload or b"<!ENTITY" in payload:
                raise ValueError("XML declarations refused")
            return ET.fromstring(payload)

        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(t.text or "" for t in item.findall(".//m:t", NS)) for item in xml("xl/sharedStrings.xml").findall("m:si", NS)]
        rows = []
        for row in xml(sheet_path).findall(".//m:sheetData/m:row", NS):
            cells = {}
            for cell in row.findall("m:c", NS):
                column = re.sub(r"\d", "", cell.attrib["r"])
                if cell.find("m:f", NS) is not None:
                    raise ValueError("formula cells require independent adjudication")
                text = cell.findtext("m:v", default="", namespaces=NS)
                if cell.attrib.get("t") == "s":
                    text = strings[int(text)]
                elif cell.attrib.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in cell.findall(".//m:t", NS))
                cells[column] = text
            if cells:
                rows.append(cells)
    header_index = next((i for i, row in enumerate(rows[:30]) if set(HEADERS) <= set(row.values())), None)
    if header_index is None:
        raise ValueError("EIA-860M schema unsupported; original header review required")
    header = rows[header_index]
    if len(set(header.values())) != len(header):
        raise ValueError("duplicate workbook headers")
    records = [{name: row.get(column, "") for column, name in header.items()} for row in rows[header_index + 1:]]
    claims, excluded, unresolved = [], 0, []
    for index, row in enumerate(records):
        state = row["Plant State"]
        if state != "PR":
            if re.fullmatch(r"[A-Z]{2}", state):
                excluded += 1
            else:
                unresolved.append({"row": index + header_index + 2, "reason": "STATE_UNRESOLVED"})
            continue
        try:
            claim = GeneratorClaim(source_system="EIA-860M", plant_id=row["Plant ID"], generator_id=row["Generator ID"],
                                   name=row["Plant Name"], nameplate_mw=float(row["Nameplate Capacity (MW)"]),
                                   status=row.get("Status", "SOURCE_STATUS_UNRESOLVED"), valid_from=effective_at,
                                   receipt_sha256=receipt_sha256)
        except ValueError:
            unresolved.append({"row": index + header_index + 2, "reason": "CLAIM_INVALID"})
        else:
            claims.append(claim)
    return {"claims": claims, "raw_rows": records, "arithmetic": {"source": len(records), "retained": len(claims),
            "excluded": excluded, "unresolved": len(unresolved)}, "unresolved": unresolved,
            "review_state": "AUDIT_ONLY", "canonical_promotion": "BLOCKED"}
