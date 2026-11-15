"""Puerto Rico solid-waste (vertedero/landfill) site registry builders.

Pure functions only: no network access and no filesystem writes. The ingest script
(``scripts/ingest_solid_waste_registry.py``) does the I/O.

Rules enforced here (ADR-0004 and the ``environmental-contaminant-certification`` skill):

* RAW source rows are preserved verbatim and kept apart from the canonical records.
* A closure year becomes ``valid_until`` and a ``SHUTDOWN`` event only for sites the source
  marks Closed. For Open sites it is a *projected* year and stays in the RAW rows.
* Cross-source matches are ``CANDIDATE_NOT_IDENTITY``. A name or a proximity never merges
  records; cross-producer identity is adjudicated by the hub.
* A filtered source query whose row count equals the unfiltered count is treated as ignored
  and fails closed. EPA ECHO silently ignores unknown filters such as ``p_naics``.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt
from typing import Any

from .environmental_exposure import derive_entity_id, stable_id

LMOP_AUTHORITY = "EPA_LMOP"
ECHO_AUTHORITY = "EPA_ECHO_FRS"
PR_STATE = "PR"
# lon min, lat min, lon max, lat max (same envelope as scripts/import_local_hydro_assets.py)
PR_BOUNDS = (-67.95, 17.7, -65.2, 18.7)
LANDFILL_NAICS = "562212"
ECHO_SIC = "4953"
# ECHO result columns: name, street, city, state, zip, registry id, county, SIC codes,
# NAICS codes, latitude, longitude, active flag.
ECHO_QCOLUMNS = "1,2,3,4,5,6,7,15,17,19,20,97"
PROXIMITY_RADIUS_M = 2000.0

LMOP_REQUIRED_HEADERS = (
    "Landfill ID",
    "Landfill Name",
    "State",
    "City",
    "County",
    "Latitude",
    "Longitude",
    "Year Landfill Opened",
    "Landfill Closure Year",
    "Current Landfill Status",
)

# Words that name a kind of place, not a particular one. They never count as a name match.
GENERIC_TOKENS = frozenset(
    {
        "A", "DE", "DEL", "EL", "LA", "LAS", "LOS", "THE", "OF", "AND", "D", "B",
        "LANDFILL", "LF", "VERTEDERO", "MUNICIPAL", "MUNICIPIO", "SOLID", "WASTE",
        "SANITARY", "REGIONAL", "LEGACY", "PARK", "ECOPARK", "WELL", "PR", "MONITORING",
        "TRANSFER", "STATION", "CORP", "INC", "CO",
    }
)

# Discovery seeds from other repositories. Never identities.
SPIDERWEB_PIN_ORIGIN = {
    "repository": "jotaele44/spiderweb-pr",
    "path": "configs/pin_registry.yaml",
    "commit": "c24b38d9fda8e5ad292f0e770330d81a19de806e",
    "evidence_tier": "T2",
    "note": "Consolidated master registry; underlying source unverified. Coordinates are "
    "rounded to 2-3 decimals (roughly 100 m to 1 km).",
}
SPIDERWEB_PINS: tuple[dict[str, Any], ...] = (
    {"seed_id": "SEED_PIN_CSWDB0002520", "name": "Toa Baja Landfill", "lat": 18.46, "lon": -66.2},
    {"seed_id": "SEED_PIN_CSWDB0002523", "name": "Ponce Landfill", "lat": 18.0, "lon": -66.61},
    {
        "seed_id": "SEED_PIN_CSWDB0003453",
        "name": "Aguadilla Regional Landfill Legacy",
        "lat": 18.425,
        "lon": -67.16,
    },
)
# Name-only seeds that fail the check: the GNIS features called "Vertedero" are populated
# places (localities), not waste sites. Kept as a recorded negative control.
REJECTED_NAME_ONLY_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "seed_id": "SEED_GNIS_1611066",
        "name": "Hacienda Vertedero",
        "county": "Juana Díaz",
        "lat": 18.1066277,
        "lon": -66.5510058,
        "reason": "GNIS feature class is Populated Place, not a waste site",
    },
    {
        "seed_id": "SEED_GNIS_1612832",
        "name": "Vertedero",
        "county": "Aibonito",
        "lat": 18.0802395,
        "lon": -66.2451679,
        "reason": "GNIS feature class is Populated Place, not a waste site",
    },
)


# Observed service behaviour that every ECHO query has to be defended against.
ECHO_SERVICE_NOTES: tuple[dict[str, str], ...] = (
    {
        "source": "EPA_ECHO",
        "observed_on": "2026-11-05",
        "note": "echo_rest_services.get_facilities silently ignores the p_naics filter: "
        "p_naics=562212 and p_naics=999999 both returned all 15256 Puerto Rico rows with "
        "Message=Success. p_sic filters correctly. Every ECHO query therefore carries a "
        "filtered-versus-unfiltered control.",
    },
)


class FilterIgnoredError(RuntimeError):
    """A source query filter had no effect, so its rows cannot define a denominator."""


@dataclass(frozen=True)
class LmopTable:
    sheet: str
    headers: tuple[str, ...]
    rows: tuple[dict[str, str], ...]


@dataclass
class RegistryRecords:
    entities: list[dict[str, Any]] = field(default_factory=list)
    geometries: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    raw_rows: list[dict[str, Any]] = field(default_factory=list)
    rejects: list[dict[str, str]] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Candidate:
    ref_id: str
    authority: str
    name: str
    municipality: str
    lat: float | None
    lon: float | None


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def canonical_sha256(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_name(text: str | None) -> str:
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", str(text or "")) if not unicodedata.combining(c)
    )
    return re.sub(r"[^A-Z0-9]+", " ", folded.upper()).strip()


def _tokens(text: str | None) -> frozenset[str]:
    return frozenset(t for t in normalize_name(text).split() if len(t) > 1 and t not in GENERIC_TOKENS)


def _year(value: str | None) -> str | None:
    match = re.fullmatch(r"\s*(\d{4})(?:\.0+)?\s*", value or "")
    return match.group(1) if match else None


def _number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _point_in_pr(lat: float | None, lon: float | None) -> tuple[float, float] | None:
    if lat is None or lon is None:
        return None
    lon_min, lat_min, lon_max, lat_max = PR_BOUNDS
    if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
        return lat, lon
    return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * 6371008.8 * asin(sqrt(a))


def lmop_release_from_url(url: str) -> str:
    match = re.search(r"/documents/(\d{4}-\d{2})/", url)
    return match.group(1) if match else "unknown"


# ---------------------------------------------------------------------------
# EPA LMOP workbook (stdlib reader: the repo has no xlsx dependency)
# ---------------------------------------------------------------------------

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DOC_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref)
    if not letters:
        raise ValueError(f"bad cell reference: {ref!r}")
    n = 0
    for ch in letters.group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(_NS + "t")) for si in root.findall(_NS + "si")]


def _sheet_titles(zf: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    target_by_id = {r.get("Id"): r.get("Target") or "" for r in rels.findall(_REL_NS + "Relationship")}
    titles: dict[str, str] = {}
    for sheet in workbook.iter(_NS + "sheet"):
        target = target_by_id.get(sheet.get(_DOC_REL_ID))
        if target:
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            titles[path] = sheet.get("name") or ""
    return titles


def _sheet_cells(xml: bytes, shared: list[str]) -> list[dict[int, str]]:
    rows: list[dict[int, str]] = []
    for row in ET.fromstring(xml).iter(_NS + "row"):
        cells: dict[int, str] = {}
        next_col = 0
        for cell in row.findall(_NS + "c"):
            kind = cell.get("t")
            value = cell.find(_NS + "v")
            if kind == "inlineStr":
                inline = cell.find(_NS + "is")
                text = "".join(t.text or "" for t in inline.iter(_NS + "t")) if inline is not None else ""
            elif value is None or value.text is None:
                text = ""
            elif kind == "s":
                text = shared[int(value.text)]
            else:
                text = value.text
            # The cell reference is optional in the spec: without one, a cell follows the previous.
            ref = cell.get("r")
            col = _col_index(ref) if ref else next_col
            cells[col] = text
            next_col = col + 1
        rows.append(cells)
    return rows


def read_lmop_workbook(data: bytes) -> LmopTable:
    """Return the worksheet that carries the LMOP header. Fails closed on drift."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("LMOP source is not an xlsx workbook") from exc
    shared = _shared_strings(zf)
    titles = _sheet_titles(zf)
    found: list[LmopTable] = []
    for path in sorted(n for n in zf.namelist() if n.startswith("xl/worksheets/sheet")):
        cells = _sheet_cells(zf.read(path), shared)
        header_at = next(
            (i for i, row in enumerate(cells) if "Landfill ID" in row.values() and "State" in row.values()),
            None,
        )
        if header_at is None:
            continue
        header_cells = cells[header_at]
        order = sorted(header_cells)
        headers = tuple(header_cells[i] for i in order)
        if not set(LMOP_REQUIRED_HEADERS) <= set(headers):
            continue
        rows = []
        for cells_row in cells[header_at + 1 :]:
            row = {header_cells[i]: cells_row.get(i, "") for i in order}
            if any(v.strip() for v in row.values()):
                rows.append(row)
        found.append(LmopTable(titles.get(path, path), headers, tuple(rows)))
    if not found:
        raise ValueError("no worksheet carries the required LMOP header columns")
    if len(found) > 1:
        raise ValueError("more than one worksheet carries the LMOP header; refusing to guess")
    return found[0]


def select_state(rows: tuple[dict[str, str], ...] | list[dict[str, str]], state: str = PR_STATE) -> list[dict[str, str]]:
    return [r for r in rows if (r.get("State") or "").strip().upper() == state]


# ---------------------------------------------------------------------------
# Canonical record builders
# ---------------------------------------------------------------------------


def _geometry_row(
    entity_id: str,
    point: tuple[float, float],
    source_record_id: str,
    review_status: str,
    notes: str,
) -> dict[str, Any]:
    lat, lon = point
    return {
        "geometry_id": stable_id("AYL_ENV_GEO", entity_id, "SOURCE_SITE_GEOMETRY", lat, lon),
        "entity_id": entity_id,
        "geometry_role": "SOURCE_SITE_GEOMETRY",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "source_crs": None,
        "canonical_crs": "OGC:CRS84",
        "valid_from": None,
        "valid_until": None,
        "transformation_notes": notes,
        "source_record_ids": [source_record_id],
        "review_status": review_status,
    }


def _raw_row(ref: str, source: str, raw: dict[str, Any], disposition: str) -> dict[str, Any]:
    return {
        "source_record_id": ref,
        "source": source,
        "disposition": disposition,
        "row_sha256": canonical_sha256(raw),
        "raw": raw,
    }


def build_lmop_records(rows: list[dict[str, str]], release: str) -> RegistryRecords:
    out = RegistryRecords()
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        lid = (raw.get("Landfill ID") or "").strip()
        name = (raw.get("Landfill Name") or "").strip()
        ref = f"EPA_LMOP:{release}:{lid}" if lid else f"EPA_LMOP:{release}:<row:{index}>"
        reject = None
        if not lid:
            reject = "MISSING_LANDFILL_ID"
        elif lid in seen:
            reject = "DUPLICATE_LANDFILL_ID"
        elif not name:
            reject = "MISSING_NAME"
        if reject:
            out.rejects.append({"source_record_id": ref, "reason": reject})
            out.raw_rows.append(_raw_row(f"{ref}:{index}", "EPA_LMOP", raw, f"REJECTED:{reject}"))
            continue
        seen.add(lid)

        status = (raw.get("Current Landfill Status") or "").strip().lower()
        opened = _year(raw.get("Year Landfill Opened"))
        closure = _year(raw.get("Landfill Closure Year"))
        reasons: list[str] = []
        valid_until = None
        if status == "closed":
            valid_until = closure
            if not closure:
                reasons.append("CLOSED_WITHOUT_CLOSURE_YEAR")
        elif status != "open":
            reasons.append("UNKNOWN_STATUS")
        point = _point_in_pr(_number(raw.get("Latitude")), _number(raw.get("Longitude")))
        if point is None:
            reasons.append("MISSING_OR_OUT_OF_ENVELOPE_COORDINATES")

        entity_id = derive_entity_id("LANDFILL", LMOP_AUTHORITY, lid)
        review_status = "needs_review" if reasons else "accepted"
        out.entities.append(
            {
                "entity_id": entity_id,
                "entity_kind": "LANDFILL",
                "name_raw": name,
                "name_normalized": normalize_name(name),
                "canonical_name": None,
                "authority": LMOP_AUTHORITY,
                "authority_id": lid,
                "municipality": (raw.get("City") or "").strip() or None,
                "valid_from": opened,
                "valid_until": valid_until,
                "source_record_ids": [ref],
                "review_status": review_status,
            }
        )
        if point is not None:
            out.geometries.append(
                _geometry_row(
                    entity_id,
                    point,
                    ref,
                    "accepted",
                    "LMOP publishes decimal-degree latitude/longitude with no stated datum, "
                    "precision or footprint; read as WGS84 (CRS84) for interchange. Unverified assumption.",
                )
            )
        if status == "closed" and closure:
            out.events.append(
                {
                    "event_id": stable_id("AYL_ENV_EVT", entity_id, "SHUTDOWN", closure),
                    "event_type": "SHUTDOWN",
                    "entity_ids": [entity_id],
                    "effective_at": closure,
                    "ended_at": None,
                    "reason_raw": f"LMOP Current Landfill Status=Closed; Landfill Closure Year={closure}",
                    "source_record_ids": [ref],
                    "review_status": "accepted",
                }
            )
        if status == "open" and closure:
            out.notes.append(
                {
                    "entity_id": entity_id,
                    "severity": "info",
                    "code": "PROJECTED_CLOSURE_YEAR_NOT_APPLIED",
                    "detail": f"Open site with Landfill Closure Year={closure}; kept in RAW rows only",
                }
            )
        for reason in reasons:
            out.notes.append({"entity_id": entity_id, "severity": "review", "code": reason, "detail": ref})
        out.raw_rows.append(_raw_row(ref, "EPA_LMOP", raw, "CANONICAL"))
    return out


def classify_echo(row: dict[str, Any]) -> tuple[str, str]:
    """Return (entity_kind, basis). Name-only classification is a discovery signal."""
    if LANDFILL_NAICS in re.findall(r"\d{6}", str(row.get("FacNAICSCodes") or "")):
        return "LANDFILL", "SOURCE_STATED_NAICS_562212"
    if {"LANDFILL", "VERTEDERO", "LF"} & set(normalize_name(row.get("FacName")).split()):
        return "LANDFILL", "NAME_ONLY"
    return "SOLID_WASTE_FACILITY", "SIC_4953_ONLY"


def echo_entity_id(registry_id: str) -> str:
    """Stable id for an ECHO source record: the authority and its RegistryID, nothing inferred.

    The entity kind of an ECHO row is inferred from its name and NAICS codes (``classify_echo``),
    so it can change between ECHO snapshots. An id derived from the kind would change with the
    classification and orphan any binding or adjudication keyed on the old one. The kind stays
    an attribute of the record; it is not part of its identity.
    """
    if not registry_id.strip():
        raise ValueError("an ECHO RegistryID is required for source-record identity")
    return stable_id("AYL_ENV", "ECHO_SOURCE_RECORD", ECHO_AUTHORITY, registry_id)


def build_echo_records(facilities: list[dict[str, Any]], query_label: str) -> RegistryRecords:
    out = RegistryRecords()
    seen: set[str] = set()
    for index, raw in enumerate(facilities):
        rid = str(raw.get("RegistryID") or "").strip()
        ref = f"EPA_ECHO:{query_label}:{rid}" if rid else f"EPA_ECHO:{query_label}:<row:{index}>"
        reject = None
        if not rid:
            reject = "MISSING_REGISTRY_ID"
        elif rid in seen:
            reject = "DUPLICATE_REGISTRY_ID"
        elif str(raw.get("FacState") or "").strip().upper() != PR_STATE:
            reject = "NOT_PUERTO_RICO"
        elif not str(raw.get("FacName") or "").strip():
            reject = "MISSING_NAME"
        if reject:
            out.rejects.append({"source_record_id": ref, "reason": reject})
            out.raw_rows.append(_raw_row(f"{ref}:{index}", "EPA_ECHO", raw, f"REJECTED:{reject}"))
            continue
        seen.add(rid)

        kind, basis = classify_echo(raw)
        name = str(raw["FacName"]).strip()
        entity_id = echo_entity_id(rid)
        out.entities.append(
            {
                "entity_id": entity_id,
                "entity_kind": kind,
                "name_raw": name,
                "name_normalized": normalize_name(name),
                "canonical_name": None,
                "authority": ECHO_AUTHORITY,
                "authority_id": rid,
                "municipality": str(raw.get("FacCity") or "").strip().title() or None,
                "valid_from": None,
                "valid_until": None,
                "source_record_ids": [ref],
                "review_status": "needs_review",
            }
        )
        out.notes.append(
            {
                "entity_id": entity_id,
                "severity": "review",
                "code": "CROSS_SOURCE_IDENTITY_UNRESOLVED",
                "detail": f"kind basis: {basis}",
            }
        )
        point = _point_in_pr(_number(raw.get("FacLat")), _number(raw.get("FacLong")))
        if point is not None:
            out.geometries.append(
                _geometry_row(
                    entity_id,
                    point,
                    ref,
                    "needs_review",
                    "EPA FRS/ECHO facility coordinates; collection method not stated by this query.",
                )
            )
        out.raw_rows.append(_raw_row(ref, "EPA_ECHO", raw, "CANONICAL"))
    return out


def echo_filter_control(filtered_rows: int, unfiltered_rows: int) -> dict[str, Any]:
    """Fail closed when a filter had no effect (EPA ECHO ignores unknown filters silently)."""
    if filtered_rows <= 0:
        raise FilterIgnoredError("ECHO filtered query returned no rows; refusing an empty denominator")
    if filtered_rows >= unfiltered_rows:
        raise FilterIgnoredError(
            f"ECHO filter had no effect: filtered={filtered_rows} unfiltered={unfiltered_rows}"
        )
    return {"filtered_rows": filtered_rows, "unfiltered_rows": unfiltered_rows, "effective": True}


# ---------------------------------------------------------------------------
# Candidate bindings (never identity) and the coverage ledger
# ---------------------------------------------------------------------------


def candidates_from_records(records: RegistryRecords) -> list[Candidate]:
    coords: dict[str, tuple[float, float]] = {}
    for geometry in records.geometries:
        lon, lat = geometry["geometry"]["coordinates"]
        coords[geometry["entity_id"]] = (lat, lon)
    out = []
    for entity in records.entities:
        lat_lon = coords.get(entity["entity_id"])
        out.append(
            Candidate(
                ref_id=entity["entity_id"],
                authority=entity["authority"],
                name=entity["name_raw"],
                municipality=normalize_name(entity.get("municipality")),
                lat=lat_lon[0] if lat_lon else None,
                lon=lat_lon[1] if lat_lon else None,
            )
        )
    return out


def seed_candidates(
    usgs_wells: list[dict[str, Any]] | None = None,
) -> tuple[list[Candidate], list[Candidate]]:
    """Return (pin candidates, well candidates). Seeds are references, not entities."""
    pins = [
        Candidate(p["seed_id"], "SPIDERWEB_PIN", p["name"], "", float(p["lat"]), float(p["lon"]))
        for p in SPIDERWEB_PINS
    ]
    wells = [
        Candidate(
            str(w["asset_id"]), "USGS_WQP", str(w.get("asset_name") or ""), "",
            _number(w.get("lat")), _number(w.get("lon")),
        )
        for w in usgs_wells or []
    ]
    return pins, wells


def _distance_m(left: Candidate, right: Candidate) -> float | None:
    if left.lat is None or left.lon is None or right.lat is None or right.lon is None:
        return None
    return haversine_m(left.lat, left.lon, right.lat, right.lon)


def _names_compatible(left: Candidate, right: Candidate) -> bool:
    """True when one place's distinguishing words are contained in the other's.

    Containment, not overlap: sharing one word is not enough ("Toa Baja" must not match
    "Toa Alta" or "Vega Baja"). It is still a discovery signal, never identity.
    """
    a, b = _tokens(left.name), _tokens(right.name)
    if not a or not b or not (a.issubset(b) or b.issubset(a)):
        return False
    return not left.municipality or not right.municipality or left.municipality == right.municipality


def _evidence(left: Candidate, right: Candidate) -> list[str]:
    evidence = []
    if _names_compatible(left, right):
        evidence.append("NORMALIZED_NAME_ONLY")
    distance = _distance_m(left, right)
    if distance is not None and distance <= PROXIMITY_RADIUS_M:
        evidence.append("PROXIMITY_ONLY")
    return evidence


def candidate_bindings(
    lefts: list[Candidate], rights: list[Candidate], binding_type: str
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Return (bindings, unbound). Every binding is CANDIDATE_NOT_IDENTITY."""
    bindings: list[dict[str, Any]] = []
    for left in lefts:
        for right in rights:
            if left.authority == right.authority:
                continue
            evidence = _evidence(left, right)
            if not evidence:
                continue
            raw_distance = _distance_m(left, right)
            distance = round(raw_distance, 1) if raw_distance is not None else None
            bindings.append(
                {
                    "binding_id": stable_id("AYL_SWB", binding_type, left.ref_id, right.ref_id),
                    "binding_type": binding_type,
                    "left_id": left.ref_id,
                    "left_authority": left.authority,
                    "right_id": right.ref_id,
                    "right_authority": right.authority,
                    "evidence_classes": evidence,
                    "distance_m": distance,
                    "adjudication_state": "CANDIDATE_NOT_IDENTITY",
                    "cardinality": "UNRESOLVED",
                }
            )
    left_deg: dict[str, set[str]] = {}
    right_deg: dict[str, set[str]] = {}
    for b in bindings:
        left_deg.setdefault(b["left_id"], set()).add(b["right_id"])
        right_deg.setdefault(b["right_id"], set()).add(b["left_id"])
    for b in bindings:
        many_rights = len(left_deg[b["left_id"]]) > 1
        many_lefts = len(right_deg[b["right_id"]]) > 1
        b["cardinality"] = (
            "N:N" if many_rights and many_lefts else "1:N" if many_rights else "N:1" if many_lefts else "1:1"
        )
    bindings.sort(key=lambda b: b["binding_id"])
    unbound = {
        "left": sorted(c.ref_id for c in lefts if c.ref_id not in left_deg),
        "right": sorted(c.ref_id for c in rights if c.ref_id not in right_deg),
    }
    return bindings, unbound


def coverage_ledger(
    *,
    lmop_total_rows: int,
    lmop_pr_rows: int,
    lmop: RegistryRecords,
    echo_rows: int,
    echo: RegistryRecords,
    bindings: list[dict[str, Any]],
    unbound: dict[str, dict[str, list[str]]],
) -> dict[str, Any]:
    """Arithmetic closure for gate G05. Raises when the counts do not close."""
    if lmop_pr_rows != len(lmop.entities) + len(lmop.rejects):
        raise ValueError("LMOP rows do not close: pr_rows != entities + rejects")
    if echo_rows != len(echo.entities) + len(echo.rejects):
        raise ValueError("ECHO rows do not close: rows != entities + rejects")
    by_cardinality: dict[str, int] = {}
    for b in bindings:
        by_cardinality[b["cardinality"]] = by_cardinality.get(b["cardinality"], 0) + 1
    return {
        "lmop": {
            "total_rows_all_states": lmop_total_rows,
            "pr_rows": lmop_pr_rows,
            "entities": len(lmop.entities),
            "needs_review": sum(1 for e in lmop.entities if e["review_status"] != "accepted"),
            "geometries": len(lmop.geometries),
            "shutdown_events": len(lmop.events),
            "rejects": len(lmop.rejects),
            "open_sites_with_projected_closure_year": sum(
                1 for n in lmop.notes if n["code"] == "PROJECTED_CLOSURE_YEAR_NOT_APPLIED"
            ),
        },
        "echo": {
            "rows": echo_rows,
            "entities": len(echo.entities),
            "landfill_kind": sum(1 for e in echo.entities if e["entity_kind"] == "LANDFILL"),
            "geometries": len(echo.geometries),
            "rejects": len(echo.rejects),
        },
        "bindings": {"total": len(bindings), "by_cardinality": by_cardinality},
        "unbound": unbound,
        "denominator_state": "PARTIAL_BOUNDED",
        "completeness_claimed": False,
        "open_residue": [
            "Puerto Rico solid-waste authority site list (no structured source located)",
            "EPA Region 2 landfill enforcement records (not yet acquired)",
            "unauthorized dumps (no source acquired)",
            "cross-source identity between LMOP and ECHO rows (hub adjudication)",
        ],
    }


def build_receipts(
    *,
    manifestations: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    ledger: dict[str, Any],
    notes: list[dict[str, Any]],
    now: str,
) -> dict[str, Any]:
    pins_origin: dict[str, Any] = dict(SPIDERWEB_PIN_ORIGIN)
    pins_origin["seeds"] = [dict(p) for p in SPIDERWEB_PINS]
    return {
        "schema_version": "aguayluz_solid_waste_receipts_v1",
        "generated_at": now,
        "result": "OPEN",
        "manifestations": manifestations,
        "source_service_notes": [dict(n) for n in ECHO_SERVICE_NOTES],
        "seed_candidates": {
            "spiderweb_pins": pins_origin,
            "rejected_name_only": [dict(s) for s in REJECTED_NAME_ONLY_SEEDS],
        },
        "candidate_bindings": bindings,
        "coverage_ledger": ledger,
        "review_notes": sorted(notes, key=lambda n: (n["entity_id"], n["code"])),
    }
