"""aguayluz.water_use: the xlsx reader, the table parsers and the read-side summaries.

Positive inputs are the real USGS data-release files, byte-identical (their SHA-256 values
are pinned in config/usgs_water_use_sources.v1.json). Cases that need a shape USGS did not
publish (a dropped row, a mislabelled header, a total that does not add up) are CONSTRUCTED
by rewriting one cell of a real file and say so.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from aguayluz import water_use as wu

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "usgs_water_use"
CONFIG = json.loads((REPO / "config" / wu.SOURCES_CONFIG).read_text(encoding="utf-8"))
SOURCES = {s["source_key"]: s for s in CONFIG["sources"]}
MUNICIPIOS = wu.load_municipios(REPO / "data" / "geo" / "pr_municipios.json")


def payload(key: str) -> bytes:
    return (FIXTURES / f"{key}.xlsx").read_bytes()


def parse(key: str, data: bytes | None = None) -> wu.ParsedTable:
    data = payload(key) if data is None else data
    return wu.parse_source(data, SOURCES[key], MUNICIPIOS, hashlib.sha256(data).hexdigest())


def rewritten(key: str, old: str, new: str, *, part: str = "xl/sharedStrings.xml") -> bytes:
    """CONSTRUCTED: the real workbook with one string replaced inside one archive member."""
    source = zipfile.ZipFile(io.BytesIO(payload(key)))
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for name in source.namelist():
            data = source.read(name)
            if name == part:
                text = data.decode("utf-8")
                assert old in text, f"{key}:{part} no longer contains {old!r}"
                data = text.replace(old, new, 1).encode("utf-8")
            out.writestr(name, data)
    return target.getvalue()


def island(table: wu.ParsedTable, provider: str = "all", category: str = "public_supply") -> dict:
    (row,) = [r for r in table.records
              if r["scope"] == "island" and r["provider"] == provider and r["category"] == category]
    return row


# ── the committed bytes are the pinned bytes ──────────────────────────────────
@pytest.mark.parametrize("key", sorted(SOURCES))
def test_fixture_bytes_match_the_pinned_sha256_and_md5(key):
    data = payload(key)
    assert hashlib.sha256(data).hexdigest() == SOURCES[key]["pinned_sha256"]
    assert hashlib.md5(data, usedforsecurity=False).hexdigest() == SOURCES[key]["expected_md5"]


# ── the figures, exactly as published ─────────────────────────────────────────
def test_2020_public_supply_is_537_surface_and_65_groundwater():
    table = parse("ps_municipio_2020")
    row = island(table)
    assert (row["surface_water_mgd"], row["groundwater_mgd"], row["total_mgd"]) == (536.64, 65.1, 601.74)
    assert row["evidence_tier"] == "T1" and row["extraction_method"] == "xlsx_cell"
    prasa = island(table, "prasa")
    assert (prasa["surface_water_mgd"], prasa["groundwater_mgd"], prasa["total_mgd"]) == (532.72, 59.7, 592.41)
    assert len([r for r in table.records if r["scope"] == "municipio"]) == wu.EXPECTED_MUNICIPIOS


def test_2015_public_supply_binds_columns_by_header_not_position():
    # 2015 lists groundwater first; a positional reader would swap the two sources.
    row = island(parse("ps_municipio_2015"))
    assert (row["surface_water_mgd"], row["groundwater_mgd"], row["total_mgd"]) == (509.78, 66.62, 576.4)


def test_2015_categories_keep_public_supply_apart_from_total_freshwater():
    table = parse("category_2015")
    assert {r["category"] for r in table.records} == set(wu.CATEGORIES)
    total = island(table, category="total_freshwater")
    assert (total["surface_water_mgd"], total["groundwater_mgd"], total["total_mgd"]) == (548.49, 122.18, 670.67)
    irrigation = island(table, category="irrigation")
    assert (irrigation["surface_water_mgd"], irrigation["groundwater_mgd"]) == (34.1, 43.48)


def test_2015_irrigation_keeps_reuse_out_of_the_withdrawal_columns():
    table = parse("irrigation_2015")
    rows = {r["municipality"]: r for r in table.records}
    assert len(rows) == 32 and all(r["scope"] == "municipio" for r in table.records)
    salinas = rows["Salinas"]
    assert (salinas["surface_water_mgd"], salinas["groundwater_mgd"], salinas["total_mgd"]) == (5.1, 7.33, 12.43)
    assert rows["Dorado"]["reuse_mgd"] == 0.58 and rows["Dorado"]["surface_water_mgd"] == 0.0
    assert table.excluded["total_row_used_for_validation"] == 1


def test_trends_table_restates_2010_public_supply_as_670():
    table = parse("trends_2015")
    row = island(table)
    assert row["year"] == 2010 and row["total_mgd"] == 670.0
    assert row["value_status"] == "restated_by_later_release"
    assert row["surface_water_mgd"] is None and row["groundwater_mgd"] is None
    assert row["record_id"].endswith(":restated")


def test_2010_transcription_is_tier_t2_and_bound_to_the_pdf_hash():
    block = CONFIG["transcription_2010"]
    table = wu.transcription_records(block, block["pinned_sha256"])
    row = island(table)
    assert (row["surface_water_mgd"], row["groundwater_mgd"], row["total_mgd"]) == (590, 87, 677.21)
    assert row["evidence_tier"] == "T2" and row["extraction_method"] == "manual_transcription"
    assert row["source_byte_sha256"] == block["pinned_sha256"]
    fresh = island(table, category="total_freshwater")
    assert (fresh["surface_water_mgd"], fresh["groundwater_mgd"], fresh["total_mgd"]) == (606.14, 117.61, 723.75)
    assert island(table, category="irrigation")["surface_water_mgd"] is None


@pytest.mark.parametrize("key", sorted(SOURCES))
def test_every_source_row_is_accounted_for(key):
    table = parse(key)
    assert table.unresolved == []
    assert table.source_rows == table.retained_rows + sum(table.excluded.values())


# ── fail closed (all CONSTRUCTED) ─────────────────────────────────────────────
def test_an_unknown_municipality_is_unresolved_not_guessed():
    table = parse("ps_municipio_2020", rewritten("ps_municipio_2020", ">Adjuntas<", ">Adjuntaz<"))
    assert len(table.unresolved) == 1 and "Adjuntaz" in table.unresolved[0]


def test_a_renamed_source_header_stops_the_run():
    data = rewritten("ps_municipio_2020", "Groundwater </t>", "Aquifer </t>")
    with pytest.raises(wu.WaterUseSourceError, match="could not bind header group"):
        parse("ps_municipio_2020", data)


def test_a_total_that_does_not_add_up_stops_the_run():
    data = rewritten("ps_municipio_2020", "<v>601.74</v>", "<v>701.74</v>", part="xl/worksheets/sheet1.xml")
    with pytest.raises(wu.WaterUseSourceError, match="does not equal total"):
        parse("ps_municipio_2020", data)


def test_a_different_table_under_the_same_name_stops_the_run():
    with pytest.raises(wu.WaterUseSourceError, match="not the expected table"):
        wu.parse_source(payload("category_2015"), SOURCES["ps_municipio_2015"], MUNICIPIOS, "0" * 64)


def test_a_missing_category_stops_the_run():
    data = rewritten("category_2015", ">Livestock<", ">Livestock (all)<")
    assert parse("category_2015", data).unresolved  # unknown label is unresolved, never dropped


def test_bytes_that_are_not_a_workbook_stop_the_run():
    with pytest.raises(wu.WaterUseSourceError, match="not an xlsx archive"):
        wu.read_xlsx_rows(b"<html>moved</html>")


# ── read side ─────────────────────────────────────────────────────────────────
def all_records() -> list[dict]:
    records = [r for key in SOURCES for r in parse(key).records if not (
        key == "category_2015" and r["category"] == "public_supply")]
    block = CONFIG["transcription_2010"]
    return records + wu.transcription_records(block, block["pinned_sha256"]).records


def test_island_summary_computes_shares_from_stored_values():
    years = {y["year"]: y for y in wu.island_summary(all_records())}
    assert sorted(years) == [2010, 2015, 2020]
    ps2020 = years[2020]["categories"]["public_supply"]["published"]
    assert (ps2020["surface_pct"], ps2020["groundwater_pct"]) == (89.2, 10.8)
    ps2015 = years[2015]["categories"]["public_supply"]["published"]
    assert (ps2015["surface_pct"], ps2015["groundwater_pct"]) == (88.4, 11.6)
    ps2010 = years[2010]["categories"]["public_supply"]
    assert (ps2010["published"]["surface_pct"], ps2010["published"]["groundwater_pct"]) == (87.1, 12.9)
    assert ps2010["restated"]["total_mgd"] == 670.0 and ps2010["restated"]["surface_pct"] is None
    assert set(years[2020]["providers"]) == {"prasa", "non_prasa"}


def test_restatements_report_the_2010_gap_without_inventing_a_reason():
    found = wu.restatements(wu.island_summary(all_records()))
    public = next(f for f in found if f["category"] == "public_supply")
    assert (public["published_total_mgd"], public["restated_total_mgd"]) == (677.21, 670.0)
    assert public["explanation"] is None and public["explanation_status"] == "not_given_by_source"


def test_municipio_table_is_sorted_and_per_year():
    table = wu.municipio_table(all_records())
    assert list(table) == ["2015", "2020"]
    assert [len(v) for v in table.values()] == [78, 78]
    assert table["2020"][0]["municipality"] == "Adjuntas"
    assert list(wu.municipio_table(all_records(), "irrigation")) == ["2015"]


def test_fold_ignores_accents_and_case():
    assert wu.fold("Juana Díaz") == wu.fold("JUANA DIAZ") == "juana diaz"
    assert wu.slug("San Germán") == "san-german"
