"""USGS water-use estimates for Puerto Rico: public supply by source, 2010 / 2015 / 2020.

The USGS Caribbean-Florida Water Science Center compiles water withdrawals every five
years. Three publications are frozen here:

* **2020** -- data release ``10.5066/P9HWON2W``, Table 1: public-supply withdrawals by
  source and municipality (xlsx).
* **2015** -- data release ``10.5066/P9POVNC6``, Tables 4, 6, 9 and 14 (xlsx).
* **2010** -- Open-File Report 2014-1117 (``10.3133/ofr20141117``). PDF only; the island
  totals are a manual transcription bound to the PDF's SHA-256.

This module is the *pure* half: it reads xlsx bytes with the standard library (no
``openpyxl`` -- the backend and the GUI-parity CI job import it without extra wheels),
turns each table into records, and summarises them for the API. Fetching and writing live
in ``scripts/ingest_usgs_water_use.py``.

Rules that shape everything here:

* **Fail closed.** A table whose title, headers, municipality count or total row is not
  exactly what the parser was written against raises :class:`WaterUseSourceError`.
* **Bind by header text, never by position.** The 2015 tables list groundwater before
  surface water; the 2020 table lists surface water first.
* **Never infer.** A value the source does not publish is ``null``. Percentages are
  computed at read time from the stored surface and groundwater values and are never stored.
* **Categories are not interchangeable.** *Public supply* is one category. *Total
  freshwater* covers every category; quoting its split as the public-supply split is the
  most common error with these figures, so both are stored and labelled.

Evidence tier is T1 for values read from a USGS data-release cell and T2 for the 2010
manual transcription.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from aguayluz.aquifer_bands import atomic_write, read_jsonl

SOURCE_ID = "usgs_pr_water_use"
UNIT = "Mgal/d"
SOURCES_CONFIG = "usgs_water_use_sources.v1.json"
SOURCES_SCHEMA = "aguayluz.usgs-water-use-sources/v1"
ESTIMATES_FILE = "water_use_estimates.jsonl"
RECEIPT_FILE = "water_use_receipt.json"
SNAPSHOT_DIRNAME = "water_use_snapshots"
RECEIPT_SCHEMA = "aguayluz.water-use-receipt/v1"
EXPECTED_MUNICIPIOS = 78
#: Published values carry two decimals and "may not add up to totals due to rounding".
SUM_TOLERANCE = 0.021

CATEGORIES: tuple[str, ...] = (
    "public_supply",
    "domestic_self_supplied",
    "irrigation",
    "livestock",
    "industrial",
    "mining",
    "thermoelectric",
    "total_freshwater",
)
CATEGORY_LABELS: dict[str, str] = {
    "public_supply": "Public supply",
    "domestic_self_supplied": "Domestic self-supplied",
    "irrigation": "Irrigation",
    "livestock": "Livestock",
    "industrial": "Industrial",
    "mining": "Mining",
    "thermoelectric": "Thermoelectric power (freshwater)",
    "total_freshwater": "Total freshwater, all categories",
}
_CATEGORY_BY_LABEL = {
    "public-supply water": "public_supply",
    "domestic self-supplied": "domestic_self_supplied",
    "irrigation": "irrigation",
    "livestock": "livestock",
    "industrial": "industrial",
    "mining": "mining",
    "thermoelectric power": "thermoelectric",
    "total": "total_freshwater",
}
_TRENDS_ROWS = {
    "public-supply water": "public_supply",
    "irrigation": "irrigation",
    "total freshwater withdrawals": "total_freshwater",
}
VALUE_STATUSES = ("as_published", "restated_by_later_release", "not_published")
EXTRACTION_METHODS = ("xlsx_cell", "manual_transcription")

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COL_RE = re.compile(r"[A-Z]+")


class WaterUseSourceError(ValueError):
    """A source file is not the document the parser was written against."""


@dataclass(frozen=True)
class SheetRow:
    number: int
    cells: Mapping[str, Any]

    def text(self, column: str) -> str:
        value = self.cells.get(column)
        return value.strip() if isinstance(value, str) else ""


@dataclass
class ParsedTable:
    """Records plus the row arithmetic that proves every source row was accounted for."""

    records: list[dict[str, Any]] = field(default_factory=list)
    source_rows: int = 0
    retained_rows: int = 0
    excluded: dict[str, int] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)

    def exclude(self, reason: str) -> None:
        self.excluded[reason] = self.excluded.get(reason, 0) + 1


# ------------------------------------------------------------------------ xlsx


def _column_index(column: str) -> int:
    index = 0
    for char in column:
        index = index * 26 + (ord(char) - 64)
    return index


def read_xlsx_rows(payload: bytes) -> list[SheetRow]:
    """Non-empty rows of the workbook's only worksheet: strings as ``str``, numbers as ``float``.

    Standard library only. Refuses a workbook with more than one worksheet, because the
    parsers below would otherwise silently read whichever came first.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise WaterUseSourceError(f"not an xlsx archive: {exc}") from exc
    with archive:
        names = archive.namelist()
        sheets = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        if len(sheets) != 1:
            raise WaterUseSourceError(f"expected exactly one worksheet, found {len(sheets)}")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))  # noqa: S314
            for item in root.findall(f"{_NS}si"):
                shared.append("".join(t.text or "" for t in item.iter(f"{_NS}t")))
        sheet = ElementTree.fromstring(archive.read(sheets[0]))  # noqa: S314
    rows: list[SheetRow] = []
    for row in sheet.iter(f"{_NS}row"):
        cells: dict[str, Any] = {}
        for cell in row.findall(f"{_NS}c"):
            match = _COL_RE.match(cell.get("r") or "")
            if match is None:
                raise WaterUseSourceError("worksheet cell without a reference")
            kind = cell.get("t")
            raw = cell.find(f"{_NS}v")
            value: Any
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in cell.iter(f"{_NS}t"))
            elif raw is None or raw.text is None:
                continue
            elif kind == "s":
                value = shared[int(raw.text)]
            elif kind in ("str", "b", "e"):
                value = raw.text
            else:
                value = float(raw.text)
            if value != "":
                cells[match.group()] = value
        if cells:
            rows.append(SheetRow(int(row.get("r") or 0), cells))
    return rows


def _number(row: SheetRow, column: str, what: str) -> float:
    """A published number. Text that is a plain number is accepted; anything else stops the run."""
    value = row.cells.get(column)
    if isinstance(value, bool) or value is None:
        raise WaterUseSourceError(f"row {row.number}: {what} is blank")
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError as exc:
            raise WaterUseSourceError(f"row {row.number}: {what} is not a number ({value!r})") from exc
    if value != value or value < 0:  # NaN or negative
        raise WaterUseSourceError(f"row {row.number}: {what} is not a non-negative number")
    return round(float(value), 4)


def _require_title(rows: list[SheetRow], needle: str, year: int | str) -> None:
    title = rows[0].text("A") if rows else ""
    if needle.lower() not in title.lower() or str(year) not in title:
        raise WaterUseSourceError(f"title cell {title!r} is not the expected table ({needle!r}, {year})")


def _source_kind(header: str) -> str | None:
    text = header.strip().lower()
    if text.startswith(("surface", "sw")):
        return "surface"
    if text.startswith(("ground", "gw")):
        return "ground"
    if text.startswith("total"):
        return "total"
    if text.startswith("reuse"):
        return "reuse"
    return None


def _grouped_columns(group_row: SheetRow, sub_row: SheetRow) -> dict[str, dict[str, str]]:
    """``{group header: {surface|ground|total|reuse: column}}`` from a two-row header.

    A group header sits over the first of its columns (the cells are merged), so each
    sub-header belongs to the nearest group header at or to its left.
    """
    groups = sorted(
        ((_column_index(c), str(v).strip()) for c, v in group_row.cells.items() if isinstance(v, str)),
    )
    result: dict[str, dict[str, str]] = {}
    for column, header in sorted(sub_row.cells.items(), key=lambda kv: _column_index(kv[0])):
        kind = _source_kind(str(header))
        owner = [name for index, name in groups if index <= _column_index(column)]
        if kind is None or not owner:
            continue
        slot = result.setdefault(owner[-1], {})
        if kind in slot:
            raise WaterUseSourceError(f"header {owner[-1]!r} has two {kind!r} columns")
        slot[kind] = column
    return result


def _pick_group(groups: Mapping[str, Mapping[str, str]], *needles: str, kinds: tuple[str, ...]) -> Mapping[str, str]:
    matches = [
        cols for name, cols in groups.items() if all(n in name.lower().replace("_", "-") for n in needles)
    ]
    if len(matches) != 1 or any(k not in matches[0] for k in kinds):
        raise WaterUseSourceError(f"could not bind header group {needles!r} with columns {kinds!r}")
    return matches[0]


def _check_sum(row: SheetRow, surface: float, ground: float, total: float, extra: float = 0.0) -> None:
    if abs(surface + ground + extra - total) > SUM_TOLERANCE:
        raise WaterUseSourceError(
            f"row {row.number}: surface {surface} + groundwater {ground}"
            + (f" + reuse {extra}" if extra else "")
            + f" does not equal total {total}"
        )


# ------------------------------------------------------------------ municipios


def fold(name: str) -> str:
    """Accent- and case-insensitive key for a municipality name."""
    stripped = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    return re.sub(r"[^a-z]+", " ", stripped.lower()).strip()


def slug(name: str) -> str:
    return fold(name).replace(" ", "-")


def load_municipios(path: Path) -> dict[str, str]:
    """``{folded name: canonical name}`` from ``data/geo/pr_municipios.json``."""
    document = json.loads(path.read_text(encoding="utf-8"))
    names = [str(item["name"]) for item in document["municipios"]]
    index = {fold(name): name for name in names}
    if len(index) != EXPECTED_MUNICIPIOS:
        raise WaterUseSourceError(f"{path} lists {len(index)} municipios, expected {EXPECTED_MUNICIPIOS}")
    return index


# --------------------------------------------------------------------- records


def _record(
    source: Mapping[str, Any],
    *,
    year: int,
    category: str,
    scope: str,
    municipality: str | None = None,
    provider: str = "all",
    surface: float | None,
    ground: float | None,
    total: float | None,
    reuse: float | None = None,
    value_status: str = "as_published",
    extraction_method: str = "xlsx_cell",
    locator: Mapping[str, Any],
    sha256: str,
    notes: Iterable[str] = (),
) -> dict[str, Any]:
    parts = ["WU", str(year), category, scope]
    if municipality is not None:
        parts.append(slug(municipality))
    parts.append(provider)
    if value_status == "restated_by_later_release":
        parts.append("restated")
    return {
        "record_id": ":".join(parts),
        "year": year,
        "category": category,
        "scope": scope,
        "municipality": municipality,
        "provider": provider,
        "surface_water_mgd": surface,
        "groundwater_mgd": ground,
        "reuse_mgd": reuse,
        "total_mgd": total,
        "unit": UNIT,
        "value_status": value_status,
        "extraction_method": extraction_method,
        "source_locator": dict(locator),
        "evidence_tier": source["evidence_tier"],
        "source_key": source["source_key"],
        "source_title": source["title"],
        "source_doi": source["doi"],
        "source_url": source["source_url"],
        "source_byte_sha256": sha256,
        "retrieved_utc": source["retrieved_utc"],
        "notes": list(notes),
    }


def parse_public_supply_municipio(
    payload: bytes, source: Mapping[str, Any], municipios: Mapping[str, str], sha256: str
) -> ParsedTable:
    """Public-supply withdrawals by source and municipality (2015 Table 6, 2020 Table 1).

    Island rows are written for PRASA, non-PRASA and all providers; municipality rows for
    all providers only.
    """
    rows = read_xlsx_rows(payload)
    year = int(source["year"])
    _require_title(rows, "public-supply water withdrawals", year)
    table = ParsedTable(source_rows=len(rows))
    header_at = next((i for i, r in enumerate(rows) if r.text("A").lower() == "municipality"), None)
    if header_at is None or header_at + 1 >= len(rows):
        raise WaterUseSourceError("no 'Municipality' header row")
    groups = _grouped_columns(rows[header_at], rows[header_at + 1])
    kinds = ("surface", "ground", "total")
    providers = {
        "prasa": _pick_group({k: v for k, v in groups.items() if "non" not in k.lower()}, "prasa", kinds=kinds),
        "non_prasa": _pick_group(groups, "non-prasa", kinds=kinds),
        "all": _pick_group({k: v for k, v in groups.items() if "prasa" not in k.lower()}, "total", kinds=kinds),
    }
    for _ in range(header_at):
        table.exclude("title_or_note")
    table.exclude("header")
    table.exclude("header")

    def values(row: SheetRow, columns: Mapping[str, str]) -> tuple[float, float, float]:
        surface = _number(row, columns["surface"], "surface water")
        ground = _number(row, columns["ground"], "groundwater")
        total = _number(row, columns["total"], "total")
        _check_sum(row, surface, ground, total)
        return surface, ground, total

    seen: set[str] = set()
    totals = 0
    sums = [0.0, 0.0, 0.0]
    island: tuple[float, float, float] | None = None
    for row in rows[header_at + 2 :]:
        label = row.text("A")
        locator = {"file": source["file_name"], "row": row.number}
        if label.lower() == "total":
            totals += 1
            table.retained_rows += 1
            for provider, columns in providers.items():
                surface, ground, total = values(row, columns)
                if provider == "all":
                    island = (surface, ground, total)
                table.records.append(_record(
                    source, year=year, category="public_supply", scope="island", provider=provider,
                    surface=surface, ground=ground, total=total, locator=locator, sha256=sha256,
                ))
            continue
        canonical = municipios.get(fold(label))
        if canonical is None:
            table.unresolved.append(f"row {row.number}: {label!r} is not a known municipality")
            continue
        if canonical in seen:
            raise WaterUseSourceError(f"row {row.number}: {canonical} appears twice")
        seen.add(canonical)
        surface, ground, total = values(row, providers["all"])
        sums = [sums[0] + surface, sums[1] + ground, sums[2] + total]
        table.retained_rows += 1
        table.records.append(_record(
            source, year=year, category="public_supply", scope="municipio", municipality=canonical,
            surface=surface, ground=ground, total=total, locator=locator, sha256=sha256,
            notes=["Withdrawals are counted in the municipality where the intake is, not where the water is used."],
        ))
    if totals != 1 or island is None:
        raise WaterUseSourceError(f"expected exactly one total row, found {totals}")
    if not table.unresolved and len(seen) != EXPECTED_MUNICIPIOS:
        raise WaterUseSourceError(f"expected {EXPECTED_MUNICIPIOS} municipalities, found {len(seen)}")
    if not table.unresolved:
        # Each of 78 rows is rounded to 0.01, so the column sums may drift from the total row.
        slack = EXPECTED_MUNICIPIOS * 0.005 + SUM_TOLERANCE
        for name, summed, published in zip(("surface", "groundwater", "total"), sums, island, strict=True):
            if abs(summed - published) > slack:
                raise WaterUseSourceError(f"municipality {name} sum {summed:.2f} disagrees with total row {published}")
    return table


def parse_category(payload: bytes, source: Mapping[str, Any], sha256: str) -> ParsedTable:
    """Freshwater withdrawals by category, island-wide (2015 Table 4)."""
    rows = read_xlsx_rows(payload)
    year = int(source["year"])
    _require_title(rows, "water withdrawals by category", year)
    table = ParsedTable(source_rows=len(rows))
    header_at = next((i for i, r in enumerate(rows) if "Freshwater" in r.cells.values()), None)
    if header_at is None or header_at + 1 >= len(rows):
        raise WaterUseSourceError("no 'Freshwater' header row")
    columns = _pick_group(_grouped_columns(rows[header_at], rows[header_at + 1]), "freshwater",
                          kinds=("surface", "ground", "total"))
    for _ in range(header_at):
        table.exclude("title_or_note")
    table.exclude("header")
    table.exclude("header")
    found: set[str] = set()
    for row in rows[header_at + 2 :]:
        category = _CATEGORY_BY_LABEL.get(row.text("A").lower())
        if category is None:
            table.unresolved.append(f"row {row.number}: unknown category {row.text('A')!r}")
            continue
        if category in found:
            raise WaterUseSourceError(f"row {row.number}: category {category} appears twice")
        found.add(category)
        surface = _number(row, columns["surface"], "surface water")
        ground = _number(row, columns["ground"], "groundwater")
        total = _number(row, columns["total"], "total")
        _check_sum(row, surface, ground, total)
        table.retained_rows += 1
        table.records.append(_record(
            source, year=year, category=category, scope="island", surface=surface, ground=ground, total=total,
            locator={"file": source["file_name"], "row": row.number}, sha256=sha256,
            notes=["Freshwater columns only; saline withdrawals (thermoelectric cooling) are not ingested."],
        ))
    if not table.unresolved and found != set(CATEGORIES):
        raise WaterUseSourceError(f"categories missing from the table: {sorted(set(CATEGORIES) - found)}")
    return table


def parse_irrigation_municipio(
    payload: bytes, source: Mapping[str, Any], municipios: Mapping[str, str], sha256: str
) -> ParsedTable:
    """Irrigation water use by source and municipality (2015 Table 9).

    Only municipalities with irrigation are listed, so there is no row-count assertion. The
    published total includes reclaimed water ("Reuse"), which is kept as its own field.
    """
    rows = read_xlsx_rows(payload)
    year = int(source["year"])
    _require_title(rows, "irrigation water use", year)
    table = ParsedTable(source_rows=len(rows))
    header_at = next((i for i, r in enumerate(rows) if r.text("A").lower() == "municipality"), None)
    if header_at is None or header_at + 1 >= len(rows):
        raise WaterUseSourceError("no 'Municipality' header row")
    columns = _pick_group(_grouped_columns(rows[header_at], rows[header_at + 1]), "irrigation water use",
                          kinds=("surface", "ground", "reuse", "total"))
    for _ in range(header_at):
        table.exclude("title_or_note")
    table.exclude("header")
    table.exclude("header")
    seen: set[str] = set()
    totals = 0
    sums = [0.0, 0.0, 0.0, 0.0]
    published: tuple[float, float, float, float] | None = None
    for row in rows[header_at + 2 :]:
        label = row.text("A")
        is_total = label.lower() == "total"
        canonical = None if is_total else municipios.get(fold(label))
        if not is_total and canonical is None:
            table.unresolved.append(f"row {row.number}: {label!r} is not a known municipality")
            continue
        if canonical is not None:
            if canonical in seen:
                raise WaterUseSourceError(f"row {row.number}: {canonical} appears twice")
            seen.add(canonical)
        surface = _number(row, columns["surface"], "surface water")
        ground = _number(row, columns["ground"], "groundwater")
        reuse = _number(row, columns["reuse"], "reuse")
        total = _number(row, columns["total"], "total")
        _check_sum(row, surface, ground, total, extra=reuse)
        if is_total:
            # Kept out of the records: Table 4 is the island figure for irrigation withdrawals,
            # and this row's total adds reclaimed water to them. It is used to check the rows above.
            totals += 1
            published = (surface, ground, reuse, total)
            table.exclude("total_row_used_for_validation")
            continue
        sums = [a + b for a, b in zip(sums, (surface, ground, reuse, total), strict=True)]
        table.retained_rows += 1
        table.records.append(_record(
            source, year=year, category="irrigation", scope="municipio", municipality=canonical,
            surface=surface, ground=ground, reuse=reuse, total=total,
            locator={"file": source["file_name"], "row": row.number}, sha256=sha256,
            notes=["Total includes reclaimed water (reuse), which is not a withdrawal."],
        ))
    if totals != 1 or published is None:
        raise WaterUseSourceError(f"expected exactly one total row, found {totals}")
    if not table.unresolved:
        slack = len(seen) * 0.005 + SUM_TOLERANCE
        for name, summed, value in zip(("surface", "groundwater", "reuse", "total"), sums, published, strict=True):
            if abs(summed - value) > slack:
                raise WaterUseSourceError(f"municipality {name} sum {summed:.2f} disagrees with total row {value}")
    return table


def parse_trends_restated(payload: bytes, source: Mapping[str, Any], sha256: str) -> ParsedTable:
    """The 2010 column of the 2015 release's trends table (Table 14).

    A later release restating an earlier year is evidence in its own right, so these rows
    are stored beside the 2010 report's own figures rather than replacing them.
    """
    rows = read_xlsx_rows(payload)
    year = int(source["year"])
    _require_title(rows, "trends in estimated water withdrawals", 2015)
    table = ParsedTable(source_rows=len(rows))
    year_columns = [
        column for row in rows[:6] for column, value in row.cells.items()
        if isinstance(value, float) and value == float(year)
    ]
    if len(year_columns) != 1:
        raise WaterUseSourceError(f"could not find a single {year} column in the trends table")
    column = year_columns[0]
    found: set[str] = set()
    for row in rows:
        category = _TRENDS_ROWS.get(row.text("A").lower())
        if category is None or column not in row.cells:
            table.exclude("not_a_tracked_row")
            continue
        if category in found:
            raise WaterUseSourceError(f"row {row.number}: {category} appears twice in the trends table")
        found.add(category)
        table.retained_rows += 1
        table.records.append(_record(
            source, year=year, category=category, scope="island", surface=None, ground=None,
            total=_number(row, column, f"{year} value"), value_status="restated_by_later_release",
            locator={"file": source["file_name"], "row": row.number, "column": column}, sha256=sha256,
            notes=[f"{year} value as restated in the 2015 release's trends table; no split by source is given there."],
        ))
    if found != set(_TRENDS_ROWS.values()):
        raise WaterUseSourceError(f"trend rows missing: {sorted(set(_TRENDS_ROWS.values()) - found)}")
    return table


def transcription_records(block: Mapping[str, Any], sha256: str) -> ParsedTable:
    """Records for the hand-transcribed 2010 values. ``sha256`` is the PDF the values were read from."""
    table = ParsedTable(source_rows=len(block["values"]))
    source = {**block, "file_name": "ofr2014-1117.pdf"}
    for value in block["values"]:
        if value["category"] not in CATEGORIES:
            table.unresolved.append(f"unknown category {value['category']!r}")
            continue
        table.retained_rows += 1
        table.records.append(_record(
            source, year=int(block["year"]), category=value["category"], scope="island",
            surface=value["surface_water_mgd"], ground=value["groundwater_mgd"], total=value["total_mgd"],
            extraction_method="manual_transcription",
            locator={"file": source["file_name"], **value["locator"]}, sha256=sha256, notes=value["notes"],
        ))
    return table


def parse_source(
    payload: bytes, source: Mapping[str, Any], municipios: Mapping[str, str], sha256: str
) -> ParsedTable:
    parser = source["parser"]
    if parser == "public_supply_municipio":
        return parse_public_supply_municipio(payload, source, municipios, sha256)
    if parser == "category":
        return parse_category(payload, source, sha256)
    if parser == "irrigation_municipio":
        return parse_irrigation_municipio(payload, source, municipios, sha256)
    if parser == "trends_restated":
        return parse_trends_restated(payload, source, sha256)
    raise WaterUseSourceError(f"unknown parser {parser!r}")


# ------------------------------------------------------------------- read side


def load_sources(config_dir: Path) -> dict[str, Any]:
    document = json.loads((config_dir / SOURCES_CONFIG).read_text(encoding="utf-8"))
    if document.get("schema_version") != SOURCES_SCHEMA:
        raise WaterUseSourceError(f"{SOURCES_CONFIG} has an unexpected schema_version")
    return document


def load_estimates(data_dir: Path) -> list[dict[str, Any]]:
    return read_jsonl(data_dir / ESTIMATES_FILE)


def load_receipt(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / RECEIPT_FILE
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def _share(part: float | None, other: float | None) -> float | None:
    if part is None or other is None or part + other <= 0:
        return None
    return round(100 * part / (part + other), 1)


def _figure(row: Mapping[str, Any]) -> dict[str, Any]:
    surface, ground = row["surface_water_mgd"], row["groundwater_mgd"]
    return {
        "record_id": row["record_id"],
        "surface_water_mgd": surface,
        "groundwater_mgd": ground,
        "reuse_mgd": row.get("reuse_mgd"),
        "total_mgd": row["total_mgd"],
        "surface_pct": _share(surface, ground),
        "groundwater_pct": _share(ground, surface),
        "value_status": row["value_status"],
        "extraction_method": row["extraction_method"],
        "evidence_tier": row["evidence_tier"],
        "source_key": row["source_key"],
        "source_doi": row["source_doi"],
        "source_locator": row["source_locator"],
        "notes": list(row.get("notes") or []),
    }


def island_summary(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per year: island-wide figures by category, with any later restatement kept beside them.

    Percentages are shares of surface + groundwater, computed here from the stored values.
    """
    years: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row["scope"] != "island" or row["provider"] not in ("all", "prasa", "non_prasa"):
            continue
        year = years.setdefault(int(row["year"]), {"year": int(row["year"]), "categories": {}, "providers": {}})
        if row["provider"] != "all":
            year["providers"][row["provider"]] = _figure(row)
            continue
        slot = year["categories"].setdefault(row["category"], {"published": None, "restated": None})
        key = "restated" if row["value_status"] == "restated_by_later_release" else "published"
        slot[key] = _figure(row)
    return [years[y] for y in sorted(years)]


def municipio_table(rows: Iterable[Mapping[str, Any]], category: str = "public_supply") -> dict[str, list[dict[str, Any]]]:
    """``{year: [municipality rows]}`` for one category, municipalities in name order."""
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["scope"] != "municipio" or row["category"] != category:
            continue
        result.setdefault(str(row["year"]), []).append({
            "municipality": row["municipality"],
            "surface_water_mgd": row["surface_water_mgd"],
            "groundwater_mgd": row["groundwater_mgd"],
            "reuse_mgd": row.get("reuse_mgd"),
            "total_mgd": row["total_mgd"],
        })
    for items in result.values():
        items.sort(key=lambda item: fold(item["municipality"]))
    return dict(sorted(result.items()))


def restatements(summary: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Years where a later release restated a total that the original publication also gives."""
    found = []
    for year in summary:
        for category, slot in year["categories"].items():
            published, restated = slot["published"], slot["restated"]
            if not published or not restated or published["total_mgd"] is None or restated["total_mgd"] is None:
                continue
            if abs(published["total_mgd"] - restated["total_mgd"]) > 0.5:
                found.append({
                    "year": year["year"],
                    "category": category,
                    "published_total_mgd": published["total_mgd"],
                    "published_source_key": published["source_key"],
                    "restated_total_mgd": restated["total_mgd"],
                    "restated_source_key": restated["source_key"],
                    "explanation": None,
                    "explanation_status": "not_given_by_source",
                })
    return found


__all__ = [
    # constants
    "CATEGORIES",
    "CATEGORY_LABELS",
    "ESTIMATES_FILE",
    "EXPECTED_MUNICIPIOS",
    "EXTRACTION_METHODS",
    "RECEIPT_FILE",
    "RECEIPT_SCHEMA",
    "SNAPSHOT_DIRNAME",
    "SOURCES_CONFIG",
    "SOURCES_SCHEMA",
    "SOURCE_ID",
    "SUM_TOLERANCE",
    "UNIT",
    "VALUE_STATUSES",
    # types
    "ParsedTable",
    "SheetRow",
    "WaterUseSourceError",
    # functions
    "atomic_write",
    "fold",
    "island_summary",
    "load_estimates",
    "load_municipios",
    "load_receipt",
    "load_sources",
    "municipio_table",
    "parse_category",
    "parse_irrigation_municipio",
    "parse_public_supply_municipio",
    "parse_source",
    "parse_trends_restated",
    "read_jsonl",
    "read_xlsx_rows",
    "restatements",
    "slug",
    "transcription_records",
]
