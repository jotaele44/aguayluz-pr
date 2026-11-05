"""Solid-waste (landfill) site registry: ``aguayluz.solid_waste`` + ``scripts/ingest_solid_waste_registry.py``.

Every built row is validated against the real schemas under ``schemas/``.

Fixture note: nothing here is a capture of a live source. The LMOP workbook is CONSTRUCTED in
memory with the real LMOP column names (so no binary fixture is committed), and the rows are
constructed: site names follow real Puerto Rico landfills, but coordinates, ids and years are
invented for the test. The ECHO rows are constructed from the exact shape the live API returns
(``FacName``, ``RegistryID``, ``FacNAICSCodes``, ...). Live behaviour was checked separately
and is recorded in ``data/solid_waste_receipts.json`` once the ingest has been run.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pytest

from aguayluz import environmental_exposure_db as db
from aguayluz import solid_waste as sw
from aguayluz.models import validate_against_schema

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import federation_export as fx  # noqa: E402
import ingest_solid_waste_registry as script  # noqa: E402

GEO = REPO / "data" / "geo" / "pr_municipios.json"
URL ="https://www.epa.gov/system/files/documents/2024-09/landfilllmopdata.xlsx"
NOW = "2026-11-05T12:00:00Z"
HEADERS = [
    "GHGRP ID", "Landfill ID", "Landfill Name", "State", "City", "County", "Latitude", "Longitude",
    "Ownership Type", "Year Landfill Opened", "Landfill Closure Year", "Current Landfill Status",
]


def lmop_row(**kw: str) -> dict[str, str]:
    row = {h: "" for h in HEADERS}
    row.update({"State": "PR", "Ownership Type": "Public", "Current Landfill Status": "Open"})
    row.update(kw)
    return row


def _col(i: int) -> str:
    out = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        out = chr(65 + rem) + out
    return out


def make_xlsx(sheets: dict[str, list[list[str]]]) -> bytes:
    """Minimal in-memory xlsx: shared strings, one worksheet per entry, real workbook rels."""
    strings: list[str] = []

    def sid(text: str) -> int:
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    sheet_xml = []
    for rows in sheets.values():
        body = []
        for r, row in enumerate(rows, start=1):
            cells = "".join(
                f'<c r="{_col(c)}{r}" t="s"><v>{sid(v)}</v></c>' for c, v in enumerate(row) if v != ""
            )
            body.append(f'<row r="{r}">{cells}</row>')
        sheet_xml.append(
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(body)}</sheetData></worksheet>"
        )
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    names = list(sheets)
    workbook = (
        f'<workbook xmlns="{ns}" xmlns:r="{rel_ns}"><sheets>'
        + "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1))
        + "</sheets></workbook>"
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(names) + 1)
        )
        + "</Relationships>"
    )
    shared = f'<sst xmlns="{ns}">' + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/sharedStrings.xml", shared)
        for i, xml in enumerate(sheet_xml, 1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", xml)
    return buf.getvalue()


def workbook(rows: list[dict[str, str]]) -> bytes:
    table = [HEADERS] + [[r.get(h, "") for h in HEADERS] for r in rows]
    return make_xlsx({"Summary": [["Landfill ID", "decoy sheet without the State column"]], "LMOP Database": table})


SITE_ROWS = [
    lmop_row(**{"Landfill ID": "2342", "Landfill Name": "Arroyo Landfill", "City": "Arroyo",
                "Latitude": "17.97", "Longitude": "-66.06", "Year Landfill Opened": "1977",
                "Landfill Closure Year": "2019", "Current Landfill Status": "Closed"}),
    lmop_row(**{"Landfill ID": "2350", "Landfill Name": "Carolina Landfill", "City": "Carolina",
                "Latitude": "18.41", "Longitude": "-65.94", "Year Landfill Opened": "1969",
                "Landfill Closure Year": "2030", "Current Landfill Status": "Open"}),
    lmop_row(**{"Landfill ID": "2360", "Landfill Name": "Ponce Landfill", "City": "Ponce",
                "Latitude": "18.0", "Longitude": "-66.61", "Year Landfill Opened": "1965"}),
    lmop_row(**{"Landfill ID": "2370", "Landfill Name": "Toa Baja LF", "City": "Toa Baja",
                "Latitude": "18.45", "Longitude": "-66.2", "Year Landfill Opened": "1974"}),
    lmop_row(**{"Landfill ID": "2371", "Landfill Name": "Toa Alta Landfill", "City": "Toa Alta",
                "Latitude": "18.38", "Longitude": "-66.25", "Year Landfill Opened": "1966"}),
    lmop_row(**{"Landfill ID": "2372", "Landfill Name": "Vega Baja Landfill", "City": "Vega Baja",
                "Latitude": "18.43", "Longitude": "-66.38", "Year Landfill Opened": "1970"}),
    lmop_row(**{"Landfill ID": "2380", "Landfill Name": "Lajas Landfill", "City": "Lajas",
                "Latitude": "18.05", "Longitude": "-67.06", "Year Landfill Opened": "1979"}),
]


def build_sites(rows: list[dict[str, str]] | None = None) -> sw.RegistryRecords:
    return sw.build_lmop_records(rows if rows is not None else SITE_ROWS, "2024-09")


def echo_row(name: str, rid: str, city: str, naics: str | None = None, **kw: Any) -> dict[str, Any]:
    row = {
        "FacName": name, "FacStreet": "n/a", "FacCity": city, "FacState": "PR", "FacZip": "00900",
        "RegistryID": rid, "FacCounty": city, "FacSICCodes": "4953", "FacNAICSCodes": naics,
        "FacLat": "18.1", "FacLong": "-66.1", "FacActiveFlag": "Y",
    }
    row.update(kw)
    return row


# ---------------------------------------------------------------------------
# LMOP workbook reader
# ---------------------------------------------------------------------------


def test_reader_picks_the_header_sheet_among_decoys_and_skips_empty_rows():
    data = make_xlsx(
        {
            "Summary": [["Landfill ID", "State"], ["decoy lacks the required headers", ""]],
            "LMOP Database": [HEADERS, [SITE_ROWS[0].get(h, "") for h in HEADERS], [""] * len(HEADERS)],
        }
    )
    table = sw.read_lmop_workbook(data)
    assert table.sheet == "LMOP Database"
    assert len(table.rows) == 1
    assert table.rows[0]["Landfill Name"] == "Arroyo Landfill"


def test_reader_fails_closed_on_schema_drift_and_non_xlsx():
    drift = make_xlsx({"LMOP Database": [["Landfill ID", "State", "Name"], ["1", "PR", "x"]]})
    with pytest.raises(ValueError, match="required LMOP header"):
        sw.read_lmop_workbook(drift)
    with pytest.raises(ValueError, match="not an xlsx"):
        sw.read_lmop_workbook(b"definitely not a zip")
    twice = make_xlsx({"A": [HEADERS], "B": [HEADERS]})
    with pytest.raises(ValueError, match="more than one worksheet"):
        sw.read_lmop_workbook(twice)


def test_select_state_excludes_other_states():
    rows = [lmop_row(State="FL", **{"Landfill ID": "9", "Landfill Name": "Elsewhere"}), SITE_ROWS[0]]
    assert [r["Landfill Name"] for r in sw.select_state(rows)] == ["Arroyo Landfill"]


# ---------------------------------------------------------------------------
# LMOP canonical records
# ---------------------------------------------------------------------------


def test_lmop_rows_validate_against_the_real_schemas():
    recs = build_sites()
    assert len(recs.entities) == len(SITE_ROWS)
    for e in recs.entities:
        validate_against_schema("environmental_entity", e)
    for g in recs.geometries:
        validate_against_schema("environmental_geometry", g)
    for ev in recs.events:
        validate_against_schema("environmental_exposure_event", ev)


def test_closed_site_gets_valid_until_and_a_shutdown_event():
    recs = build_sites()
    arroyo = next(e for e in recs.entities if e["name_raw"] == "Arroyo Landfill")
    assert arroyo["valid_from"] == "1977" and arroyo["valid_until"] == "2019"
    assert arroyo["authority"] == sw.LMOP_AUTHORITY and arroyo["authority_id"] == "2342"
    events = [ev for ev in recs.events if arroyo["entity_id"] in ev["entity_ids"]]
    assert [(ev["event_type"], ev["effective_at"]) for ev in events] == [("SHUTDOWN", "2019")]


def test_open_site_projected_closure_year_never_becomes_valid_until():
    recs = build_sites()
    carolina = next(e for e in recs.entities if e["name_raw"] == "Carolina Landfill")
    assert carolina["valid_until"] is None
    assert not [ev for ev in recs.events if carolina["entity_id"] in ev["entity_ids"]]
    codes = [n["code"] for n in recs.notes if n["entity_id"] == carolina["entity_id"]]
    assert "PROJECTED_CLOSURE_YEAR_NOT_APPLIED" in codes
    # the projected year is still preserved verbatim in the RAW rows
    raw = next(r for r in recs.raw_rows if r["source_record_id"].endswith(":2350"))
    assert raw["raw"]["Landfill Closure Year"] == "2030"


def test_bad_rows_are_rejected_or_flagged_not_silently_accepted():
    rows = [
        SITE_ROWS[2],
        lmop_row(**{"Landfill ID": "2360", "Landfill Name": "Duplicate id", "City": "Ponce"}),
        lmop_row(**{"Landfill Name": "No id", "City": "Ponce"}),
        lmop_row(**{"Landfill ID": "7", "Landfill Name": "No coordinates", "City": "Ponce"}),
        lmop_row(**{"Landfill ID": "8", "Landfill Name": "Closed no year", "City": "Ponce",
                    "Latitude": "18.0", "Longitude": "-66.6", "Current Landfill Status": "Closed"}),
        lmop_row(**{"Landfill ID": "9", "Landfill Name": "Offshore", "City": "Ponce",
                    "Latitude": "10.0", "Longitude": "-30.0"}),
    ]
    recs = build_sites(rows)
    assert {r["reason"] for r in recs.rejects} == {"DUPLICATE_LANDFILL_ID", "MISSING_LANDFILL_ID"}
    status = {e["authority_id"]: e["review_status"] for e in recs.entities}
    assert status == {"2360": "accepted", "7": "needs_review", "8": "needs_review", "9": "needs_review"}
    located = {g["entity_id"] for g in recs.geometries}
    by_id = {e["authority_id"]: e["entity_id"] for e in recs.entities}
    assert by_id["7"] not in located and by_id["9"] not in located
    assert len(recs.raw_rows) == len(rows)  # every source row is preserved, accepted or not


def test_ids_and_outputs_are_deterministic():
    first, second = build_sites(), build_sites()
    assert first.entities == second.entities
    assert first.geometries == second.geometries
    assert first.events == second.events


# ---------------------------------------------------------------------------
# ECHO
# ---------------------------------------------------------------------------


def test_echo_filter_control_fails_closed_when_the_filter_is_ignored():
    # The real failure: p_naics=562212 and p_naics=999999 both returned all 15,256 rows.
    with pytest.raises(sw.FilterIgnoredError, match="no effect"):
        sw.echo_filter_control(15256, 15256)
    with pytest.raises(sw.FilterIgnoredError, match="no rows"):
        sw.echo_filter_control(0, 15256)
    assert sw.echo_filter_control(16, 15256) == {"filtered_rows": 16, "unfiltered_rows": 15256, "effective": True}


def test_echo_rows_are_classified_and_always_routed_to_review():
    rows = [
        echo_row("CALABAZA LANDFILL", "1", "SANTA ISABEL", "562212"),
        echo_row("VERTEDERO MUNICIPAL TOA BAJA", "2", "TOA BAJA"),
        echo_row("FUNERARIA EHRET", "3", "SAN JUAN"),
        echo_row("DUP", "1", "SANTA ISABEL"),
        echo_row("OUT OF STATE", "4", "MIAMI", FacState="FL"),
        echo_row("NO ID", "", "PONCE"),
    ]
    recs = sw.build_echo_records(rows, "p_sic=4953")
    kinds = {e["authority_id"]: e["entity_kind"] for e in recs.entities}
    assert kinds == {"1": "LANDFILL", "2": "LANDFILL", "3": "SOLID_WASTE_FACILITY"}
    assert {e["review_status"] for e in recs.entities} == {"needs_review"}
    assert {r["reason"] for r in recs.rejects} == {
        "DUPLICATE_REGISTRY_ID", "NOT_PUERTO_RICO", "MISSING_REGISTRY_ID",
    }
    basis = {n["entity_id"]: n["detail"] for n in recs.notes}
    by_id = {e["authority_id"]: e["entity_id"] for e in recs.entities}
    assert basis[by_id["1"]].endswith("SOURCE_STATED_NAICS_562212")
    assert basis[by_id["2"]].endswith("NAME_ONLY")  # a name alone is a discovery signal
    for e in recs.entities:
        validate_against_schema("environmental_entity", e)
    for g in recs.geometries:
        validate_against_schema("environmental_geometry", g)


# ---------------------------------------------------------------------------
# Candidate bindings and the ledger
# ---------------------------------------------------------------------------


def test_one_shared_word_is_not_a_name_match():
    """Regression: the first live run matched the Toa Baja pin to Toa Alta and Vega Baja."""
    lmop = sw.candidates_from_records(build_sites())
    pins, _ = sw.seed_candidates()
    bindings, _ = sw.candidate_bindings(lmop, pins, "SAME_SITE_CANDIDATE")
    toa_baja_pin = [b for b in bindings if b["right_id"] == "SEED_PIN_CSWDB0002520"]
    names = {c.ref_id: c.name for c in lmop}
    assert [names[b["left_id"]] for b in toa_baja_pin] == ["Toa Baja LF"]


def test_bindings_are_candidates_never_identity_and_cardinality_is_classified():
    lmop = sw.candidates_from_records(build_sites())
    echo = sw.candidates_from_records(
        sw.build_echo_records(
            [
                echo_row("PONCE LANDFILL", "10", "PONCE", "562212", FacLat="18.0", FacLong="-66.61"),
                echo_row("SAN JUAN LF", "11", "SAN JUAN", "562212"),
            ],
            "p_sic=4953",
        )
    )
    bindings, unbound = sw.candidate_bindings(lmop, echo, "SAME_SITE_CANDIDATE")
    assert len(bindings) == 1
    b = bindings[0]
    assert b["adjudication_state"] == "CANDIDATE_NOT_IDENTITY"
    assert b["cardinality"] == "1:1"
    assert set(b["evidence_classes"]) == {"NORMALIZED_NAME_ONLY", "PROXIMITY_ONLY"}
    assert len(unbound["right"]) == 1  # San Juan has no LMOP candidate: residue, not a merge
    assert len(unbound["left"]) == len(lmop) - 1


def test_a_well_binds_to_its_landfill_by_name_containment_only_as_a_candidate():
    wells = [{"asset_id": "USGSWQ_X", "asset_name": "VERTEDERO WELL, LAJAS, PR", "lat": 18.05, "lon": -67.0}]
    _, well_cands = sw.seed_candidates(wells)
    lmop = sw.candidates_from_records(build_sites())
    bindings, _ = sw.candidate_bindings(lmop, well_cands, "RELATED_MONITORING_LOCATION_CANDIDATE")
    assert len(bindings) == 1 and bindings[0]["adjudication_state"] == "CANDIDATE_NOT_IDENTITY"


def test_n_to_one_cardinality_is_reported_when_two_sites_share_a_candidate():
    left = [sw.Candidate("A", "X", "Ponce Landfill", "", 18.0, -66.6), sw.Candidate("B", "X", "Ponce Landfill", "", 18.0, -66.6)]
    right = [sw.Candidate("R", "Y", "Ponce Landfill", "", 18.0, -66.6)]
    bindings, _ = sw.candidate_bindings(left, right, "SAME_SITE_CANDIDATE")
    assert {b["cardinality"] for b in bindings} == {"N:1"}


def test_ledger_must_close_arithmetically():
    lmop, echo = build_sites(), sw.build_echo_records([echo_row("X LANDFILL", "1", "PONCE")], "q")
    with pytest.raises(ValueError, match="LMOP rows do not close"):
        sw.coverage_ledger(lmop_total_rows=9, lmop_pr_rows=len(SITE_ROWS) + 1, lmop=lmop, echo_rows=1,
                           echo=echo, bindings=[], unbound={})
    ledger = sw.coverage_ledger(lmop_total_rows=9, lmop_pr_rows=len(SITE_ROWS), lmop=lmop, echo_rows=1,
                                echo=echo, bindings=[], unbound={})
    assert ledger["completeness_claimed"] is False and ledger["denominator_state"] == "PARTIAL_BOUNDED"
    assert ledger["lmop"]["shutdown_events"] == 1


def test_receipts_are_open_and_keep_the_rejected_name_only_seeds():
    receipts = sw.build_receipts(manifestations=[], bindings=[], ledger={}, notes=[], now=NOW)
    assert receipts["result"] == "OPEN"
    rejected = {s["name"]: s["reason"] for s in receipts["seed_candidates"]["rejected_name_only"]}
    assert set(rejected) == {"Vertedero", "Hacienda Vertedero"}
    assert all("Populated Place" in reason for reason in rejected.values())
    notes = receipts["source_service_notes"]
    assert len(notes) == 1 and "p_naics" in notes[0]["note"] and "15256" in notes[0]["note"]


# ---------------------------------------------------------------------------
# Ingest script end to end (offline)
# ---------------------------------------------------------------------------


@pytest.fixture
def offline(tmp_path: Path) -> dict[str, Path]:
    lmop = tmp_path / "lmop.xlsx"
    lmop.write_bytes(workbook(SITE_ROWS))
    echo = tmp_path / "echo.json"
    facilities = [echo_row("PONCE LANDFILL", "10", "PONCE", "562212", FacLat="18.0", FacLong="-66.61")]
    echo.write_text(json.dumps({"query": {"p_sic": "4953"}, "filtered_rows": 1, "unfiltered_rows": 500,
                                "facilities": facilities}))
    assets = tmp_path / "assets.jsonl"
    assets.write_text(json.dumps({"asset_id": "USGSWQ_X", "asset_name": "VERTEDERO WELL, LAJAS, PR",
                                  "lat": 18.05, "lon": -67.0}) + "\n")
    data = tmp_path / "data"
    data.mkdir()
    return {"lmop": lmop, "echo": echo, "assets": assets, "data": data}


def run(paths: dict[str, Path], *extra: str) -> int:
    return script.main([
        "--lmop-src", str(paths["lmop"]), "--lmop-url", URL, "--echo-src", str(paths["echo"]),
        "--assets", str(paths["assets"]), "--data-dir", str(paths["data"]), "--retrieved-at", NOW, *extra,
    ])


def test_script_writes_validated_files_and_a_second_run_changes_nothing(offline, capsys):
    assert run(offline) == 0
    data = offline["data"]
    entities = db.load("environmental_entity", data / "environmental_entities.jsonl")
    assert len(entities) == len(SITE_ROWS) + 1  # LMOP sites plus the one ECHO source record
    assert db.load("environmental_exposure_event", data / "environmental_exposure_events.jsonl")
    receipts = json.loads((data / "solid_waste_receipts.json").read_text())
    assert receipts["result"] == "OPEN"
    assert {m["source_id"] for m in receipts["manifestations"]} == {"EPA_LMOP", "EPA_ECHO"}
    assert receipts["manifestations"][0]["release"] == "2024-09"
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    assert run(offline) == 0
    assert {p.name: p.read_bytes() for p in data.iterdir()} == before  # zero new rows, byte-identical
    capsys.readouterr()


def test_rerun_replaces_this_ingests_stale_rows_but_keeps_other_authorities(offline):
    other = {
        "entity_id": "AYL_ENV_OTHER", "entity_kind": "SUPERFUND_SITE", "name_raw": "Elsewhere",
        "name_normalized": None, "canonical_name": None, "authority": "EPA_SEMS", "authority_id": "PRD1",
        "municipality": None, "valid_from": None, "valid_until": None,
        "source_record_ids": ["x"], "review_status": "accepted",
    }
    path = offline["data"] / "environmental_entities.jsonl"
    path.write_text(json.dumps(other) + "\n")
    assert run(offline) == 0
    offline["lmop"].write_bytes(workbook(SITE_ROWS[:3]))  # the source dropped four landfills
    assert run(offline) == 0
    entities = db.load("environmental_entity", path)
    names = {e["name_raw"] for e in entities}
    assert "Toa Alta Landfill" not in names  # stale row gone
    assert "Elsewhere" in names  # another authority's row untouched
    assert len(entities) == 3 + 1 + 1


def test_script_fails_closed_and_writes_nothing_when_the_echo_filter_was_ignored(offline, capsys):
    bad = json.loads(offline["echo"].read_text())
    bad["filtered_rows"], bad["unfiltered_rows"] = 15256, 15256
    offline["echo"].write_text(json.dumps(bad))
    assert run(offline) == 2
    assert "FAIL-CLOSED" in capsys.readouterr().err
    assert not list(offline["data"].iterdir())


def test_dry_run_writes_nothing(offline, capsys):
    assert run(offline, "--dry-run") == 0
    assert "dry-run: nothing written" in capsys.readouterr().out
    assert not list(offline["data"].iterdir())


# ---------------------------------------------------------------------------
# Federation export: accepted landfills project as `landfill_site`
# ---------------------------------------------------------------------------

LMOP_HASH = "ab" * 32


def registry_files(tmp_path: Path, lmop_rows: list[dict[str, str]], echo_rows: list[dict[str, Any]]):
    lmop, echo = sw.build_lmop_records(lmop_rows, "2024-09"), sw.build_echo_records(echo_rows, "p_sic=4953")
    paths = {n: tmp_path / n for n in ("entities.jsonl", "geometries.jsonl", "receipts.json")}
    paths["entities.jsonl"].write_text(
        "".join(json.dumps(e) + "\n" for e in lmop.entities + echo.entities)
    )
    paths["geometries.jsonl"].write_text(
        "".join(json.dumps(g) + "\n" for g in lmop.geometries + echo.geometries)
    )
    paths["receipts.json"].write_text(json.dumps({"manifestations": [
        {"source_id": "EPA_LMOP", "locator": URL, "byte_sha256": LMOP_HASH, "release": "2024-09"},
    ]}))
    return tuple(paths.values())


def test_export_projects_only_accepted_landfills(tmp_path):
    files = registry_files(tmp_path, SITE_ROWS, [echo_row("PONCE LANDFILL", "10", "PONCE", "562212")])
    sites = fx._load_landfill_sites(*files)
    assert {s["entity"]["authority"] for s in sites} == {sw.LMOP_AUTHORITY}  # ECHO is needs_review
    assert len(sites) == len(SITE_ROWS)
    streams = fx.build_streams([], [], "t", fx._load_geo(GEO), landfill_sites=sites)
    types = [e["entity_type"] for e in streams["entities"]]
    assert set(types) == {"landfill_site", "municipality"}
    assert types.count("landfill_site") == len(SITE_ROWS)


def test_export_row_carries_authoritative_id_status_location_and_source(tmp_path):
    sites = fx._load_landfill_sites(*registry_files(tmp_path, SITE_ROWS, []))
    streams = fx.build_streams([], [], "t", fx._load_geo(GEO), landfill_sites=sites)
    arroyo = next(e for e in streams["entities"] if e["name"] == "Arroyo Landfill")
    assert arroyo["external_ids"] == {"epa_lmop_landfill_id": "2342"}
    assert arroyo["attributes"] == {
        "site_kind": "LANDFILL", "authority": "EPA_LMOP", "municipality": "Arroyo", "status": "closed",
        "opened_year": "1977", "closed_year": "2019", "evidence_tier": "T1",
        "source_release": "2024-09", "review_status": "accepted",
    }
    assert arroyo["location"] == {"lat": 17.97, "lon": -66.06, "municipality": "Arroyo"}
    assert "geometry_precision" not in arroyo["evidence_state"]  # the source states no method; stay undeclared
    carolina = next(e for e in streams["entities"] if e["name"] == "Carolina Landfill")
    assert carolina["attributes"]["status"] == "open" and "closed_year" not in carolina["attributes"]
    source = next(s for s in streams["sources"] if s["source_id"] == arroyo["source_id"])
    assert source["source_name"] == URL and source["source_ref"] == LMOP_HASH
    assert any(
        r["relationship_type"] == "located_in" and r["source_entity_id"] == arroyo["entity_id"]
        for r in streams["relationships"]
    )


def test_export_resolves_municipality_through_geo_and_merges_with_asset_municipality(tmp_path):
    rows = [lmop_row(**{"Landfill ID": "5", "Landfill Name": "Anasco Landfill", "City": "Anasco",
                        "Latitude": "18.3", "Longitude": "-67.1"})]
    sites = fx._load_landfill_sites(*registry_files(tmp_path, rows, []))
    asset = {"asset_id": "A1", "asset_name": "Plant", "asset_type": "water", "municipality": "Añasco",
             "source_ref": "r", "confidence": 80}
    streams = fx.build_streams([asset], [], "t", fx._load_geo(GEO), landfill_sites=sites)
    munis = [e for e in streams["entities"] if e["entity_type"] == "municipality"]
    assert [m["name"] for m in munis] == ["Añasco"]  # one node, accents restored from the geo index
    site = next(e for e in streams["entities"] if e["entity_type"] == "landfill_site")
    target = next(r["target_entity_id"] for r in streams["relationships"]
                  if r["source_entity_id"] == site["entity_id"])
    assert target == munis[0]["entity_id"]


def test_export_is_unchanged_without_a_registry(tmp_path):
    missing = [tmp_path / "nope.jsonl", tmp_path / "nope2.jsonl", tmp_path / "nope.json"]
    assert fx._load_landfill_sites(*missing) == []
    assets = [{"asset_id": "A1", "asset_name": "Plant", "asset_type": "water", "municipality": "Ponce",
               "source_ref": "r", "confidence": 80}]
    assert fx.build_streams(assets, [], "t") == fx.build_streams(assets, [], "t", landfill_sites=[])


def test_export_cli_runs_on_a_registry_alone(tmp_path):
    entities, geometries, receipts = registry_files(tmp_path, SITE_ROWS, [])
    nothing = str(tmp_path / "absent.jsonl")
    out = tmp_path / "out"
    rc = fx.main([
        "--assets", nothing, "--events", nothing, "--incidents", nothing, "--live-incidents", nothing,
        "--alerts", nothing, "--crosswalk", nothing, "--dep-edges", nothing, "--geo", str(GEO),
        "--env-entities", str(entities), "--env-geometries", str(geometries),
        "--solid-waste-receipts", str(receipts), "--out", str(out), "--no-outputs",
    ])
    assert rc == 0
    rows = [json.loads(line) for line in (out / "entities.jsonl").read_text().splitlines()]
    assert sum(1 for r in rows if r["entity_type"] == "landfill_site") == len(SITE_ROWS)


def test_committed_registry_exports_every_accepted_lmop_site():
    """The frozen registry under data/ projects 32 Puerto Rico landfills, Arroyo among them."""
    sites = fx._load_landfill_sites(
        REPO / "data" / "environmental_entities.jsonl",
        REPO / "data" / "environmental_geometries.jsonl",
        REPO / "data" / "solid_waste_receipts.json",
    )
    names = {s["entity"]["name_raw"]: s for s in sites}
    assert len(sites) == 32 and "Arroyo Landfill" in names
    assert names["Arroyo Landfill"]["status"] == "closed"
    assert all(s["location"] for s in sites) and all(s["source_hash"] for s in sites)


# ---------------------------------------------------------------------------
# The committed snapshot (data/) and the denominator manifest
# ---------------------------------------------------------------------------

DATA = REPO / "data"
RESEARCH = REPO / "research" / "environmental_exposure"


def test_committed_registry_is_structurally_sound_and_still_open():
    report = db.graph_integrity(
        entities_path=DATA / "environmental_entities.jsonl",
        geometries_path=DATA / "environmental_geometries.jsonl",
        events_path=DATA / "environmental_exposure_events.jsonl",
        observations_path=DATA / "absent_observations.jsonl",
        relationships_path=DATA / "absent_relationships.jsonl",
    )
    assert report["structural_integrity_state"] == "PASS" and report["arithmetic_closes"] is True
    assert report["error_count"] == 0
    assert report["corpus_certification_state"] == "OPEN"


def test_committed_receipts_close_arithmetically_and_never_claim_completeness():
    receipts = json.loads((DATA / "solid_waste_receipts.json").read_text(encoding="utf-8"))
    ledger = receipts["coverage_ledger"]
    assert receipts["result"] == "OPEN" and ledger["completeness_claimed"] is False
    assert ledger["lmop"]["pr_rows"] == ledger["lmop"]["entities"] + ledger["lmop"]["rejects"]
    assert ledger["echo"]["rows"] == ledger["echo"]["entities"] + ledger["echo"]["rejects"]
    assert receipts["candidate_bindings"]
    assert {b["adjudication_state"] for b in receipts["candidate_bindings"]} == {"CANDIDATE_NOT_IDENTITY"}
    for manifest in receipts["manifestations"]:
        assert manifest["retrieved_at"] and manifest["evidence_tier"] == "T1"
        assert manifest.get("byte_sha256") or manifest.get("response_sha256")


def test_no_open_site_in_the_real_snapshot_has_a_closure_date():
    """The rule checked on real rows: LMOP lists a projected closure year for 10 Open sites."""
    entities = {e["authority_id"]: e for e in db.load("environmental_entity", DATA / "environmental_entities.jsonl")
                if e["authority"] == sw.LMOP_AUTHORITY}
    raw_rows = [json.loads(line) for line in (DATA / "solid_waste_source_rows.jsonl").read_text().splitlines()]
    lmop_raw = [r["raw"] for r in raw_rows if r["source"] == "EPA_LMOP" and r["disposition"] == "CANONICAL"]
    assert len(lmop_raw) == len(entities)
    projected = 0
    for raw in lmop_raw:
        entity = entities[raw["Landfill ID"]]
        if raw["Current Landfill Status"] == "Open":
            assert entity["valid_until"] is None
            projected += bool(raw["Landfill Closure Year"].strip())
        else:
            assert entity["valid_until"] == raw["Landfill Closure Year"].strip()[:4]
    assert projected > 0  # the trap is present in this snapshot, so the assertion above is meaningful


def test_denominator_v2_delta_stays_open_and_points_at_real_evidence():
    data = json.loads((RESEARCH / "source_denominator_progress.v2.json").read_text(encoding="utf-8"))
    assert data["overall_state"] == "OPEN" and data["completeness_claimed"] is False
    (update,) = data["solid_waste_subscope_updates"]
    assert update["family"] == "PR_SOLID_WASTE" and update["state"] != "EXHAUSTED"
    assert update["remaining_open"] and (REPO / update["evidence_manifest"]).is_file()
    # the unresolved gap is named, and it is true: ECHO lists a landfill that LMOP does not
    assert any("CALABAZA LANDFILL" in item for item in update["remaining_open"])
    names = {e["entity_id"]: e["name_raw"] for e in db.load("environmental_entity", DATA / "environmental_entities.jsonl")}
    receipts = json.loads((DATA / "solid_waste_receipts.json").read_text(encoding="utf-8"))
    echo_only = {names[i] for i in receipts["coverage_ledger"]["unbound"]["lmop_vs_echo"]["right"]}
    assert "CALABAZA LANDFILL" in echo_only
