"""PRDNER aquifer threshold bands for the south-coast USGS observation wells.

The USGS Caribbean-Florida Water Science Center publishes a page,
"Groundwater Levels at Selected Observation Wells in the South Coast of Puerto Rico"
(``pr.water.usgs.gov/drought/hydro_conditions_selected_wells.html``), that colours each
of five wells' depth-to-water against four condition bands -- Optimum, Observation,
Operational Adjustment, Critical -- and attributes the thresholds to the Puerto Rico
Department of Natural and Environmental Resources (PRDNER). The band edges are
hard-coded in the page's inline JavaScript; nothing else publishes them.

This module is the *pure* half of that integration: it parses the page, classifies a
depth against a well's bands, and reads the committed registry and the latest local
reading. It is stdlib-only on purpose -- the backend and the GUI-parity CI job import it
without httpx or the geospatial stack. Fetching and writing live in
``scripts/ingest_prdner_well_bands.py``.

Three rules shape everything here:

* **Fail closed.** The thresholds come from scraping one page's JavaScript, so a page
  that no longer looks exactly like the one the parser was written against must stop the
  run, not be guessed at. Every structural assumption is asserted and raises
  :class:`BandPageError`.
* **Classification is total.** The page's own label ladders fall through for a depth
  beyond their last rung. A depth at or beyond the deepest edge is ``critical`` here, a
  negative depth (a flowing artesian well) is ``above_optimum``, and NaN is rejected.
* **Parameter 72019 only.** Depth *below* land surface. A level *above* datum (62610)
  runs in the opposite direction and would invert every class, so a reading is accepted
  only when its parameter code is exactly ``72019``.

Evidence tier is T2: operational documentation published by USGS and attributed to
PRDNER, with no effective date, adoption date or method stated on the page.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SOURCE_ID = "prdner_aquifer_bands"
#: The ``.html`` form. The extensionless URL 301s to a generic Water Science Center page.
PAGE_URL = "https://pr.water.usgs.gov/drought/hydro_conditions_selected_wells.html"
PARAMETER_CODE = "72019"
EXPECTED_WELLS = 5
EVIDENCE_TIER = "T2"
DEPTH_CONVENTION = (
    "feet below land surface, positive down (the source page plots the same numbers negated)"
)
AUTHORITY_CLAIM = (
    "Puerto Rico Department of Natural and Environmental Resources (PRDNER), as attributed "
    "by the USGS page; not independently verified"
)
ATTRIBUTION_TEXT = (
    "Thresholds established by the Puerto Rico Department of Natural and Environmental Resources"
)
EFFECTIVE_DATE_STATUS = "not_published_by_source"

#: Band edges are published to 0.01 ft. The page carries each edge twice (chart ``ranges``
#: and a label ladder); a disagreement within rounding is recorded, a larger one means the
#: source disagrees with itself and the run stops.
LADDER_TOLERANCE_FT = 0.011

#: The page is a static set of constants, so it is re-read weekly; two missed weekly runs
#: make the registry STALE.
MAX_AGE_SECONDS = 14 * 24 * 3600
#: Readings carry a calendar day only; two days is the staleness line at that resolution.
READING_STALE_DAYS = 2

REGISTRY_FILE = "aquifer_band_registry.jsonl"
RECEIPT_FILE = "aquifer_band_receipt.json"
SNAPSHOT_DIRNAME = "aquifer_band_snapshots"
RECEIPT_SCHEMA = "aguayluz.aquifer-band-receipt/v1"
READING_FILES = ("usgs_continuous_readings.jsonl", "groundwater_levels.jsonl")

#: Shallow to deep. ``above_optimum`` is the unlabelled green band shallower than Optimum:
#: the page's legend has no entry for it, so it is never given a PRDNER name.
CLASSES: tuple[str, ...] = (
    "above_optimum",
    "optimum",
    "observation",
    "operational_adjustment",
    "critical",
)
CLASS_LABELS: dict[str, str] = {
    "above_optimum": "Shallower than Optimum (no legend entry at source)",
    "optimum": "Optimum",
    "observation": "Observation",
    "operational_adjustment": "Operational Adjustment",
    "critical": "Critical",
}
#: Chart ``ranges`` colour -> class.
_RANGE_COLORS = {
    "#468C00": "above_optimum",
    "#007FFF": "optimum",
    "#FFFF00": "observation",
    "#FFA64D": "operational_adjustment",
    "#D90000": "critical",
}
#: Label-ladder colour -> class.
_LADDER_COLORS = {
    "#468C00": "above_optimum",
    "#99CCFF": "optimum",
    "#FFFF99": "observation",
    "#FFDCB8": "operational_adjustment",
    "#F09999": "critical",
}
#: The legend binds a colour to a PRDNER name, and the class names rest on it, so a change
#: to it is as fatal as a change to the numbers.
_LEGEND = (
    ("Blue", "Optimum condition"),
    ("Yellow", "Observation"),
    ("Orange", "Operational Adjustment"),
    ("Red", "Critical condition"),
)


class BandPageError(ValueError):
    """The page no longer matches the structure this parser was written against."""


@dataclass(frozen=True)
class Band:
    """One condition band, in feet below land surface: ``shallow_ft <= depth < deep_ft``."""

    cls: str
    shallow_ft: float
    deep_ft: float

    def to_json(self) -> dict[str, Any]:
        return {"class": self.cls, "shallow_ft": self.shallow_ft, "deep_ft": self.deep_ft}


@dataclass(frozen=True)
class ParsedWell:
    site_no: str
    chart_id: str
    title: str
    bands: tuple[Band, ...]
    ladder: tuple[tuple[float, str], ...]
    reference_url: str
    discrepancies: tuple[str, ...]

    @property
    def axis_max_ft(self) -> float:
        return self.bands[-1].deep_ft


@dataclass(frozen=True)
class ParsedPage:
    parameter_code: str
    wells: tuple[ParsedWell, ...]


# --------------------------------------------------------------------- parsing

_NUM = r"-?\d+(?:\.\d+)?"
_CHART_OPEN = re.compile(r'\$\("#(wellBulletChart\d+)"\)\.jqxBulletChart\(\s*\{')
_BAND = re.compile(
    rf'\{{\s*startValue:\s*({_NUM})\s*,\s*endValue:\s*({_NUM})\s*,\s*color:\s*"(#[0-9A-Fa-f]{{6}})"'
)
_SITE_REF = re.compile(r'site\.indexOf\("(\d{15})"\)')
_CHART_VAL = re.compile(r'\$\("#(wellBulletChart\d+)"\)\.jqxBulletChart\("val"')
_RUNG = re.compile(rf'value\s*<\s*({_NUM})\)\s*\{{\s*labelColor\s*=\s*"(#[0-9A-Fa-f]{{6}})"')
_IV_URL = re.compile(
    r'waterservices\.usgs\.gov/nwis/iv/\?[^"]*?sites=([0-9,\s]+?)\s*(?:&|")[^"]*?parameterCd=(\d{5})'
)
_ANCHOR = re.compile(r'href=["\']([^"\']*AWLSites\.asp\?S=(\d{15})[^"\']*)["\']')
_LEGEND_PAIR = re.compile(r'alt="(Blue|Yellow|Orange|Red) square icon"\s*>\s*([^<]+?)\s*</td>')
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def _balanced(text: str, open_index: int) -> str:
    """The ``{...}`` block starting at ``open_index``, ignoring braces inside strings."""
    depth = 0
    quote: str | None = None
    i = open_index
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_index : i + 1]
        i += 1
    raise BandPageError("unbalanced braces in a chart definition")


def _strip_js_comments(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", js)


def _bands_from_ranges(chart_id: str, ranges: list[tuple[str, str, str]]) -> tuple[Band, ...]:
    if len(ranges) != len(CLASSES):
        raise BandPageError(f"{chart_id}: expected {len(CLASSES)} bands, found {len(ranges)}")
    parsed: list[tuple[float, float, str]] = []
    for start, end, color in ranges:
        cls = _RANGE_COLORS.get(color.upper())
        if cls is None:
            raise BandPageError(f"{chart_id}: unrecognised band colour {color}")
        # The page plots depth negated: -13.65..-12.00 is 12.00..13.65 ft below surface.
        edges = sorted((abs(float(start)), abs(float(end))))
        parsed.append((round(edges[0], 2), round(edges[1], 2), cls))
    parsed.sort(key=lambda b: (b[0], b[1]))
    if [b[2] for b in parsed] != list(CLASSES):
        raise BandPageError(f"{chart_id}: band classes are not in shallow-to-deep order {CLASSES}")
    if parsed[0][0] != 0.0:
        raise BandPageError(f"{chart_id}: shallowest band does not start at the land surface")
    for earlier, later in zip(parsed, parsed[1:], strict=False):  # adjacent pairs: lengths differ by one
        if abs(earlier[1] - later[0]) > 1e-9:
            raise BandPageError(f"{chart_id}: bands are not contiguous ({earlier[1]} vs {later[0]})")
    for shallow, deep, cls in parsed:
        if not shallow < deep:
            raise BandPageError(f"{chart_id}: empty or inverted {cls} band {shallow}..{deep}")
    return tuple(Band(cls, shallow, deep) for shallow, deep, cls in parsed)


def _compare_ladder(bands: tuple[Band, ...], ladder: tuple[tuple[float, str], ...]) -> list[str]:
    """Differences between the two copies of the thresholds the page carries.

    Within :data:`LADDER_TOLERANCE_FT` they are recorded; beyond it the source contradicts
    itself and :class:`BandPageError` is raised.
    """
    notes: list[str] = []
    ladder_edges = {cls: round(edge, 2) for edge, cls in ladder}
    for band in bands:
        if band.cls not in ladder_edges:
            notes.append(f"{band.cls}: absent from the label ladder (chart range ends {band.deep_ft})")
            continue
        diff = abs(ladder_edges[band.cls] - band.deep_ft)
        if diff > LADDER_TOLERANCE_FT:
            raise BandPageError(
                f"{band.cls}: chart range ends {band.deep_ft} ft but the label ladder says "
                f"{ladder_edges[band.cls]} ft"
            )
        if diff > 1e-9:
            notes.append(f"{band.cls}: chart range ends {band.deep_ft} ft, label ladder {ladder_edges[band.cls]} ft")
    return notes


def parse_page(payload: bytes) -> ParsedPage:
    """Parse the hydro-conditions page. Raises :class:`BandPageError` on any structural drift."""
    html = payload.decode("latin-1")  # 1:1 with the bytes that were hashed; the parsed text is ASCII
    visible = _HTML_COMMENT.sub("", html)

    if ATTRIBUTION_TEXT not in visible:
        raise BandPageError("the PRDNER attribution is missing; the thresholds' authority cannot be stated")
    legend = tuple((c, n.strip()) for c, n in _LEGEND_PAIR.findall(visible))
    if legend != _LEGEND:
        raise BandPageError(f"legend changed: {legend!r}")

    scripts = [s for s in _SCRIPT.findall(html) if "jqxBulletChart(" in s]
    if len(scripts) != 1:
        raise BandPageError(f"expected one inline chart script, found {len(scripts)}")
    js = _strip_js_comments(scripts[0])

    iv = _IV_URL.search(js)
    if not iv:
        raise BandPageError("the page's live-value request was not found")
    iv_sites = tuple(s.strip() for s in iv.group(1).split(",") if s.strip())
    if iv.group(2) != PARAMETER_CODE:
        raise BandPageError(f"page reads parameter {iv.group(2)}, expected {PARAMETER_CODE} (depth below surface)")

    titles: dict[str, str] = {}
    chart_bands: dict[str, tuple[Band, ...]] = {}
    for match in _CHART_OPEN.finditer(js):
        block = _balanced(js, match.end() - 1)
        if "ranges:" not in block:
            continue  # an update call (pointer/target), not a definition
        chart_id = match.group(1)
        if chart_id in chart_bands:
            raise BandPageError(f"{chart_id} is defined twice")
        title = re.search(r'title:\s*"([^"]*)"', block)
        if not title:
            raise BandPageError(f"{chart_id}: no title")
        titles[chart_id] = re.sub(r"(?:&nbsp;|\s)+$", "", title.group(1))
        chart_bands[chart_id] = _bands_from_ranges(chart_id, _BAND.findall(block))
    if len(chart_bands) != EXPECTED_WELLS:
        raise BandPageError(f"expected {EXPECTED_WELLS} charts, found {len(chart_bands)}")

    # Site -> chart comes from the page's own handler, never from list position.
    starts = list(_SITE_REF.finditer(js))
    ladders: dict[str, tuple[str, tuple[tuple[float, str], ...]]] = {}
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(js)
        segment = js[match.start() : end]
        chart = _CHART_VAL.search(segment)
        if not chart:
            raise BandPageError(f"site {match.group(1)}: no chart update follows its label ladder")
        found: list[tuple[float, str]] = []
        for edge, color in _RUNG.findall(segment):
            cls = _LADDER_COLORS.get(color.upper())
            if cls is None:
                raise BandPageError(f"site {match.group(1)}: unrecognised label colour {color}")
            found.append((round(float(edge), 2), cls))
        if not found:
            raise BandPageError(f"site {match.group(1)}: no label ladder rungs")
        if match.group(1) in ladders:
            raise BandPageError(f"site {match.group(1)} has two label ladders")
        ladders[match.group(1)] = (chart.group(1), tuple(found))

    if len(ladders) != EXPECTED_WELLS or set(ladders) != set(iv_sites) or len(iv_sites) != EXPECTED_WELLS:
        raise BandPageError(
            f"site lists disagree: request {sorted(iv_sites)}, label ladders {sorted(ladders)}"
        )
    ladder_charts = [chart for chart, _ in ladders.values()]
    if len(set(ladder_charts)) != EXPECTED_WELLS or set(ladder_charts) != set(chart_bands):
        raise BandPageError("the label ladders do not map one-to-one onto the chart definitions")

    anchors: dict[str, str] = {}
    for href, site in _ANCHOR.findall(visible):
        if not href.startswith("https://groundwaterwatch.usgs.gov/"):
            raise BandPageError(f"unexpected reference host in {href}")
        anchors.setdefault(site, href)
    if set(anchors) != set(iv_sites):
        raise BandPageError(f"reference links {sorted(anchors)} do not match the wells {sorted(iv_sites)}")

    wells = []
    for site, (chart_id, rungs) in ladders.items():
        bands = chart_bands[chart_id]
        wells.append(
            ParsedWell(
                site_no=site,
                chart_id=chart_id,
                title=titles[chart_id],
                bands=bands,
                ladder=rungs,
                reference_url=anchors[site],
                discrepancies=tuple(_compare_ladder(bands, rungs)),
            )
        )
    wells.sort(key=lambda w: int(w.chart_id.removeprefix("wellBulletChart")))
    return ParsedPage(parameter_code=iv.group(2), wells=tuple(wells))


# -------------------------------------------------------------- classification


def classify(bands: Iterable[Band], depth_ft: float) -> str:
    """Condition class for a depth below land surface. Total over every finite or infinite depth.

    ``shallow <= depth < deep`` (the page's own ``value < X`` ladder). A depth at or past the
    deepest edge is ``critical``; a negative depth is ``above_optimum``. NaN is an error.
    """
    if isinstance(depth_ft, bool) or not isinstance(depth_ft, (int, float)) or math.isnan(depth_ft):
        raise ValueError(f"depth must be a number, got {depth_ft!r}")
    ordered = list(bands)
    if not ordered:
        raise ValueError("no bands")
    if depth_ft < ordered[0].shallow_ft:
        return ordered[0].cls
    for band in ordered:
        if band.shallow_ft <= depth_ft < band.deep_ft:
            return band.cls
    return ordered[-1].cls


def critical_onset_ft(bands: Iterable[Band]) -> float:
    for band in bands:
        if band.cls == "critical":
            return band.shallow_ft
    raise ValueError("no critical band")


def margin_to_critical_ft(bands: Iterable[Band], depth_ft: float) -> float:
    """Feet of headroom before the Critical onset; negative means already past it."""
    return round(critical_onset_ft(bands) - depth_ft, 2)


def material_digest(bands: Iterable[Band], parameter_code: str = PARAMETER_CODE) -> str:
    """Stable digest of what makes a registry revision material: parameter, classes and edges."""
    payload = [parameter_code, [[b.cls, round(b.shallow_ft, 2), round(b.deep_ft, 2)] for b in bands]]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def bands_from_json(items: Iterable[Mapping[str, Any]]) -> tuple[Band, ...]:
    return tuple(Band(str(i["class"]), float(i["shallow_ft"]), float(i["deep_ft"])) for i in items)


# --------------------------------------------------------------------- storage


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"non-object JSONL row in {path}")
            rows.append(row)
    return rows


def atomic_write(path: Path, text: str) -> None:
    """Write-then-rename, so a crash never leaves a half-written registry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if path.exists():
            os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def current_registry(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """The latest revision per site."""
    current: dict[str, dict[str, Any]] = {}
    for row in rows:
        site = str(row["site_no"])
        if site not in current or int(row["revision"]) > int(current[site]["revision"]):
            current[site] = dict(row)
    return current


def load_receipt(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / RECEIPT_FILE
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def freshness(receipt: Mapping[str, Any] | None, now: datetime) -> dict[str, Any]:
    """FRESH / STALE / FAILED / NEVER, with the same meaning as the hydromet plane's."""
    base = {"max_age_seconds": MAX_AGE_SECONDS}
    if not receipt:
        return {"state": "NEVER", "age_seconds": None, **base}
    last = _parse_utc(receipt.get("last_success_utc"))
    age = (now - last).total_seconds() if last else None
    if receipt.get("last_status") == "FAIL":
        state = "FAILED"
    elif age is None:
        state = "NEVER"
    elif age > MAX_AGE_SECONDS:
        state = "STALE"
    else:
        state = "FRESH"
    return {"state": state, "age_seconds": age, **base}


def _reading_order(row: Mapping[str, Any]) -> tuple[str, str]:
    """(day, intraday token). Continuous ids end in a 14-digit timestamp; daily values have none."""
    reading_id = str(row.get("reading_id") or "")
    token = reading_id.rsplit("_", 1)[-1] if "_usgscv_" in reading_id else ""
    return (str(row.get("observed_date") or ""), token)


def latest_readings(sites: Iterable[str], data_dir: Path) -> dict[str, dict[str, Any]]:
    """Newest 72019 reading per site across the continuous and daily-value files.

    One pass over each file. Only parameter ``72019`` in feet is accepted -- see the module
    docstring for why 62610 must never reach a class.
    """
    wanted = set(sites)
    best: dict[str, dict[str, Any]] = {}
    for name in READING_FILES:
        for row in read_jsonl(data_dir / name):
            site = str(row.get("site_no") or "")
            value = row.get("value")
            if (
                site not in wanted
                or row.get("metric") != "groundwater_level"
                or row.get("parameter_code") != PARAMETER_CODE
                or row.get("unit") != "ft"
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not row.get("observed_date")
            ):
                continue
            if site not in best or _reading_order(row) > _reading_order(best[site]):
                best[site] = row
    return best


def well_view(
    registry_row: Mapping[str, Any], reading: Mapping[str, Any] | None, today: date
) -> dict[str, Any]:
    """Everything the API serves for one well, derived from the registry row and a reading."""
    bands = bands_from_json(registry_row["bands"])
    view: dict[str, Any] = {
        "site_no": registry_row["site_no"],
        "asset_id": registry_row["asset_id"],
        "name": registry_row["site_name_source"],
        "municipality": registry_row.get("municipality"),
        "revision": registry_row["revision"],
        "first_observed_utc": registry_row.get("first_observed_utc"),
        "source_byte_sha256": registry_row.get("source_byte_sha256"),
        "ladder_discrepancies": list(registry_row.get("ladder_discrepancies") or []),
        "bands": [b.to_json() for b in bands],
        "axis_max_ft": bands[-1].deep_ft,
        "critical_onset_ft": critical_onset_ft(bands),
        "reference_url": registry_row.get("reference_url"),
        "reading": None,
        "class": None,
        "class_label": None,
        "margin_to_critical_ft": None,
    }
    if reading is None:
        return view
    depth = float(reading["value"])
    observed = date.fromisoformat(str(reading["observed_date"]))
    cls = classify(bands, depth)
    view.update(
        {
            "reading": {
                "value_ft": depth,
                "observed_date": observed.isoformat(),
                "provisional": bool(reading.get("provisional")),
                "stale": (today - observed).days > READING_STALE_DAYS,
                "reading_id": reading.get("reading_id"),
                "source_ref": reading.get("source_ref"),
            },
            "class": cls,
            "class_label": CLASS_LABELS[cls],
            "margin_to_critical_ft": margin_to_critical_ft(bands, depth),
        }
    )
    return view


__all__ = [
    "AUTHORITY_CLAIM",
    "Band",
    "BandPageError",
    "CLASSES",
    "CLASS_LABELS",
    "ParsedPage",
    "ParsedWell",
    "PAGE_URL",
    "PARAMETER_CODE",
    "classify",
    "current_registry",
    "critical_onset_ft",
    "freshness",
    "latest_readings",
    "margin_to_critical_ft",
    "material_digest",
    "parse_page",
    "well_view",
]
