from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape
import io
import zipfile

import pytest

from aguayluz.source_intelligence.adapters.base import RawArtifact
from aguayluz.source_intelligence.adapters.eia860m import (
    EIA860MAdapter,
    compare_identity_snapshots,
)
from aguayluz.source_intelligence.health import evaluate_health
from aguayluz.source_intelligence.readiness import (
    GATE_WEIGHTS,
    current_backend_readiness,
    score_backend_readiness,
)
from aguayluz.source_intelligence.runtime import (
    freeze_health_receipt,
    load_health_receipts,
    persist_source_manifestation,
    verify_source_manifestation,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "source_intelligence"
    / "eia860m_pr_hydro_2026_jan_feb.known_good.json"
)
MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = [
    "Plant State",
    "Plant ID",
    "Generator ID",
    "Plant Name",
    "Nameplate Capacity (MW)",
    "Net Summer Capacity (MW)",
    "Net Winter Capacity (MW)",
    "Energy Source Code",
    "Prime Mover Code",
    "Status",
    "Technology",
]


def _column_name(index: int) -> str:
    result = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _sheet_xml(rows: list[list[object]]) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>',
    ]
    for row_number, row in enumerate(rows, start=1):
        parts.append(f'<row r="{row_number}">')
        for column, value in enumerate(row):
            ref = f"{_column_name(column)}{row_number}"
            text = escape("" if value is None else str(value))
            parts.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'
            )
        parts.append("</row>")
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def _xlsx(
    operating_rows: list[list[object]],
    retired_rows: list[list[object]] | None = None,
    *,
    headers: list[str] | None = None,
) -> bytes:
    header = headers or HEADERS
    preamble = [["Preliminary Monthly Electric Generator Inventory"], ["Form EIA-860M"]]
    operating = [*preamble, header, *operating_rows]
    retired = [*preamble, header, *(retired_rows or [])]
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>'
        '<sheet name="Operating" sheetId="1" r:id="rId1"/>'
        '<sheet name="Retired" sheetId="2" r:id="rId2"/>'
        '</sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet2.xml"/>'
        '</Relationships>'
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", _sheet_xml(operating))
        archive.writestr("xl/worksheets/sheet2.xml", _sheet_xml(retired))
    return out.getvalue()


def _artifact(content: bytes, retrieved_at: str = "2026-11-02T18:00:00Z") -> RawArtifact:
    return RawArtifact(
        source_family_id="EIA_860M",
        locator="https://www.eia.gov/electricity/data/eia860m/archive/xls/january_generator2026.xlsx",
        content=content,
        media_type=MEDIA,
        retrieved_at_iso=retrieved_at,
    )


def test_parser_detects_preamble_and_retains_only_pr_hydro() -> None:
    rows = [
        ["PR", "61225", "1", "Caonillas", "9", "9", "9", "WAT", "HY", "OP", "Conventional Hydroelectric"],
        ["PR", "61231", "1", "Toro Negro", "1.4", "1.4", "1.4", "WAT", "HY", "(SB) Standby", "Conventional Hydroelectric"],
        ["TX", "100", "1", "Other", "5", "5", "5", "WAT", "HY", "OP", "Conventional Hydroelectric"],
        ["PR", "99999", "1", "Gas", "5", "5", "5", "NG", "CT", "OP", "Natural Gas Fired Combined Cycle"],
    ]
    adapter = EIA860MAdapter()
    artifact = _artifact(_xlsx(rows))
    parsed = adapter.parse_pr_hydro(artifact)
    assert [row["identity"]["key"] for row in parsed] == ["61225::1", "61231::1"]
    assert parsed[0]["raw"]["Plant ID"] == "61225"
    assert parsed[1]["normalized"]["status_code"] == "SB"
    assert len(adapter.fingerprint_schema(artifact)) == 64


def test_duplicate_identity_fails_closed() -> None:
    row = ["PR", "61225", "1", "Caonillas", "9", "9", "9", "WAT", "HY", "OP", "Conventional Hydroelectric"]
    with pytest.raises(ValueError, match="duplicate Plant ID"):
        EIA860MAdapter().parse_pr_hydro(_artifact(_xlsx([row, row])))


def test_null_generator_id_fails_closed() -> None:
    row = ["PR", "61225", "", "Caonillas", "9", "9", "9", "WAT", "HY", "OP", "Conventional Hydroelectric"]
    with pytest.raises(ValueError, match="null plant/generator identity"):
        EIA860MAdapter().parse_pr_hydro(_artifact(_xlsx([row])))


def test_zero_pr_hydro_rows_fails_closed() -> None:
    row = ["TX", "61225", "1", "Other", "9", "9", "9", "WAT", "HY", "OP", "Conventional Hydroelectric"]
    with pytest.raises(ValueError, match="expected nonzero"):
        EIA860MAdapter().parse_pr_hydro(_artifact(_xlsx([row])))


def test_missing_required_header_fails_closed() -> None:
    headers = [value for value in HEADERS if value != "Generator ID"]
    row = ["PR", "61225", "Caonillas", "9", "9", "9", "WAT", "HY", "OP", "Conventional Hydroelectric"]
    with pytest.raises(ValueError, match="header row"):
        EIA860MAdapter().parse_pr_hydro(_artifact(_xlsx([row], headers=headers)))


def test_known_good_jan_feb_replay_closes_identity_arithmetic() -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    january = document["snapshots"]["2026-01"]
    february = document["snapshots"]["2026-02"]
    assert january["raw_source_bytes_embedded"] is False
    assert february["raw_source_bytes_embedded"] is False
    result = compare_identity_snapshots(january["rows"], february["rows"])
    assert result == {
        "intersection": 20,
        "a_only": 0,
        "b_only": 0,
        "union": 20,
        "symmetric_difference": 0,
        "changed": 0,
        "changed_keys": [],
        "a_nameplate_mw": 98.1,
        "b_nameplate_mw": 98.1,
    }
    statuses = [row["status_code"] for row in january["rows"]]
    assert statuses.count("OP") == 19
    assert statuses.count("SB") == 1


def test_content_addressed_manifestations_are_immutable_and_distinct_by_retrieval(tmp_path) -> None:
    raw = _xlsx([
        ["PR", "61225", "1", "Caonillas", "9", "9", "9", "WAT", "HY", "OP", "Conventional Hydroelectric"]
    ])
    first = persist_source_manifestation(tmp_path, _artifact(raw, "2026-01-23T00:00:00Z"))
    second = persist_source_manifestation(tmp_path, _artifact(raw, "2026-02-23T00:00:00Z"))
    assert first.byte_sha256 == second.byte_sha256
    assert first.manifestation_id != second.manifestation_id
    assert len(list((tmp_path / "objects" / "sha256").rglob(first.byte_sha256))) == 1
    assert len(list((tmp_path / "manifestations" / "EIA_860M").glob("*.json"))) == 2
    verify_source_manifestation(tmp_path, first)
    object_path = (
        tmp_path / "objects" / "sha256" / first.byte_sha256[:2] / first.byte_sha256
    )
    object_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_source_manifestation(tmp_path, first)


def test_health_receipts_are_content_addressed_and_replayable(tmp_path) -> None:
    checked = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
    health = evaluate_health(
        "EIA_860M",
        now=checked,
        last_check=checked,
        last_success=checked - timedelta(days=1),
        record_count=20,
        expected_nonzero=True,
    )
    receipt_hash, path = freeze_health_receipt(tmp_path, health, checked_at=checked)
    assert path.name == f"{receipt_hash}.json"
    second_hash, second_path = freeze_health_receipt(tmp_path, health, checked_at=checked)
    assert (receipt_hash, path) == (second_hash, second_path)
    rows = load_health_receipts(tmp_path, "EIA_860M")
    assert len(rows) == 1
    assert rows[0]["health"]["state"] == "HEALTHY"


def test_backend_readiness_requires_every_gate() -> None:
    current = current_backend_readiness(coverage_matrix_ready=True)
    assert current.score == 10
    assert not current.frontend_authorized
    assert "real_jan_feb_source_bytes" in current.unresolved
    passed = score_backend_readiness({gate: "PASS" for gate in GATE_WEIGHTS})
    assert passed.score == 100
    assert passed.frontend_authorized
    assert passed.unresolved == ()
