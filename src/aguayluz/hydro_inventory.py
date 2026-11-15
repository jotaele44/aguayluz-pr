"""Puerto Rico hydrologic feature inventory: claims, features, links, conflicts, coverage.

The inventory exists to reflect what is known about Puerto Rico's water features, not what
any one source says. Every source statement is kept as a **claim**. Claims are grouped into
a **feature** only on identity-grade evidence:

* **I1** the same authority identifier (one USGS site number seen through the Water Data
  API, the Water Quality Portal ``USGS-…`` id, or an existing ``USGSGW_``/``USGSFM_`` asset);
* **I2** a source publishing another source's identifier;
* **I3** the same dataset in a newer release.

Names and distances never merge anything. They produce ``CANDIDATE_SAME_FEATURE`` links,
which is why feature counts are reported as a range: ``features_upper`` keeps every
candidate apart, ``features_lower`` merges every I4 candidate (name and proximity
together, or an analyst's written name equivalence). Weaker I5 candidates (proximity only)
are listed but do not move the range, because well fields would chain them together.

Source disagreements are **conflicts**: rows that carry every source's value and are shown,
not resolved. The one exception, the datum of the USGS HA 730-N polygons, is marked as
resolved by measured evidence, with the numbers.

This module is stdlib-only so the backend and the GUI-parity job can import it. Geometry
processing that needs shapely or pyproj lives in ``scripts/ingest_hydro_aquifers.py``.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import tempfile
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

SOURCES_CONFIG = "hydro_inventory_sources.v1.json"
HYDRO_DIR = "hydro"
FEATURES_FILE = "features_{}.jsonl"  # one file per feature type, to stay under the commit size limit
LINKS_FILE = "links.jsonl"
CONFLICTS_FILE = "conflicts.jsonl"
RECEIPT_FILE = "inventory_receipt.json"
AQUIFER_GEOJSON = "pr_aquifers.geojson"
RECEIPT_SCHEMA = "aguayluz.hydro-inventory-receipt/v1"

FEATURE_TYPES: tuple[str, ...] = ("aquifer", "well", "spring", "stream", "watercourse", "waterfall", "waterbody",
                                  "reservoir", "intake", "gauge", "watershed")
PHASE_ENUMERATED: tuple[str, ...] = FEATURE_TYPES
MONITORING_STATES: tuple[str, ...] = ("MONITORED_NOW", "HISTORICAL_ONLY", "NO_DATA", "READINGS_ABSENT_ON_SERVER")
#: A discrete-measurement well is visited a few times a year; a year plus a month is one cycle.
MONITORED_NOW_DAYS = 400
WELL_PROXIMITY_M = 150.0
GW_SITE_TYPES = ("GW", "GW-TH", "GW-MW", "GW-CR")
COORDINATE_CONFLICT_M = 100.0
READING_FILES = ("groundwater_levels.jsonl", "usgs_field_measurements_readings.jsonl", "usgs_continuous_readings.jsonl")
PR_BOUNDS = (-68.0, 17.5, -65.1, 18.7)

GENERIC_NAME_TOKENS = frozenset({
    "A", "DE", "DEL", "EL", "LA", "LAS", "LOS", "THE", "OF", "AND", "D", "B", "PR", "WELL", "POZO", "NO",
    "NUM", "RD", "KM", "CARR", "BO", "BARRIO", "SECTOR", "PIEZOMETER", "OBS", "OBSERVATION", "TEST", "HOLE",
    "URB", "URBANIZACION", "CALLE", "AVE", "AVENIDA", "MUNICIPIO", "MUNICIPALITY",
})


# ── small utilities ───────────────────────────────────────────────────────────
def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def normalize_name(text: str | None) -> str:
    folded = "".join(c for c in unicodedata.normalize("NFKD", str(text or "")) if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", folded.upper()).strip()


_ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6", "VII": "7", "VIII": "8", "IX": "9", "X": "10"}
_ADDRESS = re.compile(r"\b(KM|CARR|ROAD|RD|CALLE|INT|HWY|CARRETERA)\b")


def name_tokens(text: str | None, stop: frozenset[str] = frozenset()) -> frozenset[str]:
    """Distinguishing words. Numbers are kept and Roman numerals read as numbers: well 4 is not well 5."""
    out = set()
    for t in normalize_name(text).split():
        t = _ROMAN.get(t, t)
        if t not in GENERIC_NAME_TOKENS and t not in stop:
            out.add(t.lstrip("0") or "0")
    return frozenset(out)


def names_compatible(a: str | None, b: str | None, stop: frozenset[str] = frozenset()) -> bool:
    """Containment of distinguishing words, never overlap: 'Toa Baja' must not match 'Toa Alta'.

    ``stop`` removes context words, such as municipio names, that two unrelated sites share.
    """
    left, right = name_tokens(a, stop), name_tokens(b, stop)
    return bool(left and right and (left <= right or right <= left))


def well_names(feature: Mapping[str, Any]) -> list[str]:
    """Names usable for matching: never a road address.

    The Puerto Rico EQB stations in the Water Quality Portal put an address in the name field
    and the well's name in the identifier (``PREQB_GW-CABO ROJO II``), so the identifier
    suffix is used for them.
    """
    names = []
    fid = str(feature.get("feature_id", ""))
    if fid.startswith("WELL:WQP:"):
        suffix = fid.split(":", 2)[2].split("-", 1)[-1]
        if not suffix.replace(" ", "").isdigit():
            names.append(suffix)
    raw = feature.get("display_name")
    if raw and not _ADDRESS.search(normalize_name(raw)):
        names.append(raw)
    return names


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def atomic_write(path: Path, text: str) -> None:
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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    atomic_write(path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                               for r in rows))


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if v not in (None, "", [], {})}
    return value


# ── claims ────────────────────────────────────────────────────────────────────
def claim(*, source_key: str, authority: str, feature_type: str, source_feature_id: str, name_raw: str | None,
          evidence_tier: str, manifestation_sha256: str, retrieved_utc: str, lat: float | None = None,
          lon: float | None = None, attributes: Mapping[str, Any] | None = None, disposition: str = "RETAINED",
          exclusion_reason: str | None = None, extraction_method: str = "parsed") -> dict[str, Any]:
    """One source's statement about one feature, as received."""
    if feature_type not in FEATURE_TYPES:
        raise ValueError(f"unknown feature type {feature_type}")
    return {
        "claim_id": "HCL_" + canonical_sha256([source_key, source_feature_id])[:16],
        "source_key": source_key,
        "authority": authority,
        "feature_type": feature_type,
        "source_feature_id": source_feature_id,
        "name_raw": name_raw,
        "lat": None if lat is None else round(float(lat), 6),
        "lon": None if lon is None else round(float(lon), 6),
        "attributes": _clean(dict(attributes or {})),
        "evidence_tier": evidence_tier,
        "extraction_method": extraction_method,
        "manifestation_sha256": manifestation_sha256,
        "retrieved_utc": retrieved_utc,
        "disposition": disposition,
        "exclusion_reason": exclusion_reason,
    }


CLAIMS_FORMAT = "aguayluz.hydro-claims/v1"
_SHARED = ("source_key", "authority", "evidence_tier", "extraction_method", "retrieved_utc")


def write_claims(path: Path, claims: list[dict[str, Any]]) -> None:
    """Write claims with the fields every claim in a file shares stored once.

    A file holds one source. Each row keeps what varies (id, name, location, attributes,
    disposition) plus an index into the file's list of manifestations, so the per-claim
    SHA-256 survives without repeating 64 characters on every row. ``read_claims`` restores
    the full claim dicts, including ``claim_id``.
    """
    ids = [c["claim_id"] for c in claims]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate claim ids in {path.name}")
    ordered = sorted(claims, key=lambda c: (c["source_key"], c["source_feature_id"]))
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for c in ordered:
        groups.setdefault(tuple(c[k] for k in _SHARED), []).append(c)
    lines = []
    for shared, rows in groups.items():
        shas = sorted({c["manifestation_sha256"] for c in rows})
        lines.append({"_header": CLAIMS_FORMAT, **dict(zip(_SHARED, shared, strict=True)), "manifestations": shas,
                      "rows": len(rows)})
        for c in rows:
            row: dict[str, Any] = {"id": c["source_feature_id"], "t": c["feature_type"], "m": shas.index(c["manifestation_sha256"])}
            if c["name_raw"] is not None:
                row["n"] = c["name_raw"]
            if c["lat"] is not None:
                row["ll"] = [c["lat"], c["lon"]]
            if c["attributes"]:
                row["a"] = c["attributes"]
            if c["disposition"] != "RETAINED":
                row["x"] = c["exclusion_reason"]
            lines.append(row)
    atomic_write(path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                               for r in lines))


def read_claims(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    header: dict[str, Any] | None = None
    remaining = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "_header" in row:
            if remaining:
                raise ValueError(f"{path.name}: a block ended {remaining} rows short")
            if row["_header"] != CLAIMS_FORMAT:
                raise ValueError(f"{path.name}: unknown claims format {row['_header']}")
            header, remaining = row, row["rows"]
            continue
        if header is None or remaining <= 0:
            raise ValueError(f"{path.name}: claim row outside a block")
        remaining -= 1
        ll = row.get("ll") or [None, None]
        c = claim(source_key=header["source_key"], authority=header["authority"], feature_type=row["t"],
                  source_feature_id=row["id"], name_raw=row.get("n"), evidence_tier=header["evidence_tier"],
                  manifestation_sha256=header["manifestations"][row["m"]], retrieved_utc=header["retrieved_utc"],
                  lat=ll[0], lon=ll[1], attributes=row.get("a"), extraction_method=header["extraction_method"],
                  disposition="EXCLUDED" if "x" in row else "RETAINED", exclusion_reason=row.get("x"))
        out.append(c)
    if remaining:
        raise ValueError(f"{path.name}: the last block ended {remaining} rows short")
    return out


def close_ledger(*, source_rows: int, retained: int, excluded: Mapping[str, int], unresolved: int) -> dict[str, Any]:
    """SOURCE = RETAINED + EXCLUDED + UNRESOLVED, or the run stops."""
    total_excluded = sum(excluded.values())
    accounted = retained + total_excluded + unresolved
    if accounted != source_rows:
        raise ValueError(f"ledger does not close: {source_rows} rows, {accounted} accounted")
    return {"source": source_rows, "retained": retained, "excluded": total_excluded,
            "excluded_by_reason": dict(sorted(excluded.items())), "unresolved": unresolved,
            "accounted": accounted, "delta": 0, "state": "PASS"}


def write_fail_receipt(path: Path, stage: str, now: str, error: str) -> None:
    previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    previous.update({"stage": stage, "last_attempt_utc": now, "last_status": "FAIL", "last_error": error})
    atomic_write(path, json.dumps(previous, indent=2, sort_keys=True, default=str) + "\n")


# ── geometry (stdlib) ─────────────────────────────────────────────────────────
def _ring_contains(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def _polygons(geometry: Mapping[str, Any]) -> list[list[list[list[float]]]]:
    if geometry.get("type") == "Polygon":
        return [geometry["coordinates"]]
    if geometry.get("type") == "MultiPolygon":
        return list(geometry["coordinates"])
    return []


class PolygonIndex:
    """Point-in-polygon over GeoJSON features, holes respected, with a bounding-box prefilter."""

    def __init__(self, features: Iterable[Mapping[str, Any]]) -> None:
        self._items = []
        for feature in features:
            polys = _polygons(feature.get("geometry") or {})
            if not polys:
                continue
            xs = [p[0] for poly in polys for p in poly[0]]
            ys = [p[1] for poly in polys for p in poly[0]]
            self._items.append(((min(xs), min(ys), max(xs), max(ys)), polys, feature.get("properties") or {}))

    def containing(self, lon: float, lat: float) -> list[Mapping[str, Any]]:
        hits = []
        for (x0, y0, x1, y1), polys, props in self._items:
            if not (x0 <= lon <= x1 and y0 <= lat <= y1):
                continue
            for poly in polys:
                if _ring_contains(lon, lat, poly[0]) and not any(_ring_contains(lon, lat, h) for h in poly[1:]):
                    hits.append(props)
                    break
        return hits


# ── building the inventory ────────────────────────────────────────────────────
def _feature(feature_id: str, feature_type: str, claims: list[dict[str, Any]], evidence: list[dict[str, Any]],
             **extra: Any) -> dict[str, Any]:
    order = {"T1": 0, "T2": 1, "T3": 2, "T4": 3}
    best = min(claims, key=lambda c: (order.get(c["evidence_tier"], 9), c["source_key"]))
    located = [c for c in claims if c["lat"] is not None]
    anchor = min(located, key=lambda c: (order.get(c["evidence_tier"], 9), c["source_key"])) if located else None
    return {
        "feature_id": feature_id,
        "feature_type": feature_type,
        "display_name": best["name_raw"],
        "claim_ids": sorted(c["claim_id"] for c in claims),
        "sources": sorted({c["source_key"] for c in claims}),
        "lat": anchor["lat"] if anchor else None,
        "lon": anchor["lon"] if anchor else None,
        "location_source": anchor["source_key"] if anchor else None,
        "identity_evidence": evidence,
        **_clean(extra),
    }


def aquifer_feature_id(source_feature_id: str) -> str:
    return f"AQ:{source_feature_id}"


def build_aquifers(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """No published identifier crosses these sources, so each aquifer claim is its own feature."""
    out = []
    for c in claims:
        if c["feature_type"] != "aquifer" or c["disposition"] != "RETAINED":
            continue
        a = c["attributes"]
        out.append(_feature(aquifer_feature_id(c["source_feature_id"]), "aquifer", [c], [], authority=c["authority"],
                            aq_code=a.get("aq_code") or a.get("aquifer_code") or a.get("national_aquifer_code"),
                            island=a.get("island"), area_km2=a.get("area_km2"), municipios=a.get("municipios"),
                            system=a.get("system"), name_is_source_class_only=a.get("name_is_source_class_only")))
    return sorted(out, key=lambda f: f["feature_id"])


def build_wells(site_claims: list[dict[str, Any]], wqp_claims: list[dict[str, Any]],
                sdwis_claims: list[dict[str, Any]], asset_ids_by_site: Mapping[str, list[str]]
                ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Well features, grouping claims only on the USGS site number (I1). Returns (features, conflicts)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in site_claims:
        if c["disposition"] == "RETAINED" and c["attributes"].get("site_type_code") in GW_SITE_TYPES:
            groups.setdefault(f"WELL:USGS:{c['source_feature_id']}", []).append(c)
    for c in wqp_claims:
        if c["disposition"] != "RETAINED":
            continue
        site = c["attributes"].get("usgs_site_no")
        key = f"WELL:USGS:{site}" if site else f"WELL:WQP:{c['source_feature_id']}"
        groups.setdefault(key, []).append(c)
    for c in sdwis_claims:
        if c["disposition"] == "RETAINED":
            groups.setdefault(f"WELL:SDWIS:{c['source_feature_id']}", []).append(c)
    features, conflicts = [], []
    for key in sorted(groups):
        members = groups[key]
        site = key.split(":", 2)[2] if key.startswith("WELL:USGS:") else None
        ev = []
        if site and len({c["source_key"] for c in members}) > 1:
            ev.append({"tier": "I1", "key": f"USGS_SITE:{site}", "claim_ids": sorted(c["claim_id"] for c in members)})
        assets = list(asset_ids_by_site.get(site, [])) if site else []
        if assets:
            ev.append({"tier": "I1", "key": f"USGS_SITE:{site}", "utility_asset_ids": assets})
        usgs = next((c for c in members if c["source_key"] == "usgs_monitoring_locations"), None)
        attrs = usgs["attributes"] if usgs else members[0]["attributes"]
        feature = _feature(key, "well", members, ev, site_no=site, utility_asset_ids=assets,
                           site_type_code=attrs.get("site_type_code"), aquifer_code=attrs.get("aquifer_code"),
                           national_aquifer_code=attrs.get("national_aquifer_code"),
                           well_depth_ft=attrs.get("well_constructed_depth"), municipio=attrs.get("county_name"),
                           activity=attrs.get("facility_activity_code"), located=None)
        feature["located"] = feature["lat"] is not None
        features.append(feature)
        located = [c for c in members if c["lat"] is not None]
        for i, a in enumerate(located):
            for b in located[i + 1:]:
                d = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
                if d > COORDINATE_CONFLICT_M:
                    conflicts.append(conflict(
                        f"coordinate:{key}:{a['source_key']}:{b['source_key']}", [key], "location", "coordinate",
                        [{"claim_id": a["claim_id"], "source_key": a["source_key"], "value": [a["lat"], a["lon"]]},
                         {"claim_id": b["claim_id"], "source_key": b["source_key"], "value": [b["lat"], b["lon"]]}],
                        note=f"{round(d)} m apart for the same USGS site"))
    return features, conflicts


def build_springs(site_claims: list[dict[str, Any]], wqp_claims: list[dict[str, Any]],
                  gnis_claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Spring features: USGS sites (I1 with their WQP copies) and GNIS names, never merged on names."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in site_claims:
        if c["disposition"] == "RETAINED" and c["feature_type"] == "spring":
            groups.setdefault(f"SPRING:USGS:{c['source_feature_id']}", []).append(c)
    for c in wqp_claims:
        if c["disposition"] == "RETAINED":
            site = c["attributes"].get("usgs_site_no")
            groups.setdefault(f"SPRING:USGS:{site}" if site else f"SPRING:WQP:{c['source_feature_id']}", []).append(c)
    for c in gnis_claims:
        if c["disposition"] == "RETAINED" and c["feature_type"] == "spring":
            groups.setdefault(f"SPRING:GNIS:{c['source_feature_id']}", []).append(c)
    out = []
    for key in sorted(groups):
        members = groups[key]
        site = key.split(":", 2)[2] if key.startswith("SPRING:USGS:") else None
        ev = [{"tier": "I1", "key": f"USGS_SITE:{site}", "claim_ids": sorted(c["claim_id"] for c in members)}] \
            if site and len({c["source_key"] for c in members}) > 1 else []
        usgs = next((c for c in members if c["source_key"] == "usgs_monitoring_locations"), None)
        attrs = usgs["attributes"] if usgs else members[0]["attributes"]
        f = _feature(key, "spring", members, ev, site_no=site, aquifer_code=attrs.get("aquifer_code"),
                     national_aquifer_code=attrs.get("national_aquifer_code"),
                     municipio=attrs.get("county_name"), located=None)
        f["located"] = f["lat"] is not None
        out.append(f)
    return out


def point_candidates(items: list[dict[str, Any]], radius_m: float = WELL_PROXIMITY_M) -> list[dict[str, Any]]:
    """Name+proximity (I4) and proximity-only (I5) candidates between features from different namespaces."""
    def ns(f: Mapping[str, Any]) -> str:
        return f["feature_id"].split(":")[1]

    stop = frozenset(t for f in items for t in normalize_name(f.get("municipio")).split())
    located = sorted((f for f in items if f["lat"] is not None), key=lambda f: f["feature_id"])
    out = []
    for i, a in enumerate(located):
        for b in located[i + 1:]:
            if ns(a) == ns(b):
                continue
            d = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
            if d > radius_m:
                continue
            named = names_compatible(a["display_name"], b["display_name"], stop)
            out.append(link("CANDIDATE_SAME_FEATURE", a["feature_id"], b["feature_id"], "CANDIDATE",
                            ["NORMALIZED_NAME", "PROXIMITY"] if named else ["PROXIMITY_ONLY"],
                            tier="I4" if named else "I5", distance_m=round(d, 1)))
    return out


def build_surface(claims_by_source: Mapping[str, list[dict[str, Any]]]
                  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Streams, watercourses, waterfalls, waterbodies, reservoirs, intakes, gauges and watersheds.

    Returns (features, links, conflicts, notes). Identity rules as everywhere: NHD and GNIS merge
    on the GNIS id NHD publishes (I2); NWS gauges merge with USGS sites on the USGS id NWS
    publishes (I2); nothing merges on names or distance.
    """
    features, links, conflicts = [], [], []
    gnis = [c for c in claims_by_source.get("usgs_gnis_names", []) if c["disposition"] == "RETAINED"]

    # streams: every mapped reach; the named watercourse groups them through the published GNIS id
    reach_gnis: dict[str, list[str]] = {}
    for c in claims_by_source.get("usgs_nhd_flowlines", []):
        if c["disposition"] != "RETAINED":
            continue
        a = c["attributes"]
        fid = f"STREAM:NHD:{c['source_feature_id']}"
        features.append(_feature(fid, "stream", [c], [], huc8=a.get("huc8"), flow_type=a.get("flow_type"),
                                 lengthkm=a.get("lengthkm"), gnis_id=a.get("gnis_id"), located=c["lat"] is not None))
        if a.get("gnis_id"):
            reach_gnis.setdefault(a["gnis_id"], []).append(fid)
    for c in gnis:
        if c["feature_type"] not in ("watercourse", "waterfall"):
            continue
        prefix = "WATERCOURSE" if c["feature_type"] == "watercourse" else "WATERFALL"
        fid = f"{prefix}:GNIS:{c['source_feature_id']}"
        reaches = reach_gnis.get(c["source_feature_id"], [])
        features.append(_feature(fid, c["feature_type"], [c], [], gnis_class=c["attributes"].get("gnis_class"),
                                 municipio=c["attributes"].get("county_name"), reaches=len(reaches) or None,
                                 located=c["lat"] is not None))
        for r in reaches:
            links.append(link("REACH_OF_WATERCOURSE", r, fid, "AUTHORITATIVE", ["NHD_PUBLISHES_GNIS_ID"], tier="I2"))
    named_gnis = {c["source_feature_id"] for c in gnis if c["feature_type"] == "watercourse"}
    unmatched = sorted(set(reach_gnis) - named_gnis)

    # waterbodies and reservoirs: NHD polygons grouped by the GNIS id they publish, plus GNIS points
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in claims_by_source.get("usgs_nhd_waterbodies", []):
        gid = c["attributes"].get("gnis_id")
        groups.setdefault(f"GNIS:{gid}" if gid else f"NHD:{c['source_feature_id']}", []).append(c)
    for c in gnis:
        if c["feature_type"] in ("waterbody", "reservoir"):
            groups.setdefault(f"GNIS:{c['source_feature_id']}", []).append(c)
    for key in sorted(groups):
        members = groups[key]
        nhd = [c for c in members if c["source_key"] == "usgs_nhd_waterbodies"]
        kinds = {c["feature_type"] for c in members}
        kind = "reservoir" if any(c["feature_type"] == "reservoir" for c in (nhd or members)) else "waterbody"
        fid = f"{kind.upper()}:{key}"
        ev = [{"tier": "I2", "key": key, "claim_ids": sorted(c["claim_id"] for c in members)}] if len(members) > 1 else []
        features.append(_feature(fid, kind, members, ev, nhd_polygons=len(nhd) or None,
                                 areasqkm=round(sum(float(c["attributes"].get("areasqkm") or 0) for c in nhd), 4) or None,
                                 water_type=",".join(sorted({c["attributes"].get("water_type") or c["attributes"].get("gnis_class")
                                                             for c in members})), located=True))
        if len(kinds) > 1:
            conflicts.append(conflict(f"waterbody_kind:{key}", [fid], "waterbody_kind", "classification",
                                      [{"claim_id": c["claim_id"], "source_key": c["source_key"],
                                        "value": c["attributes"].get("water_type") or c["attributes"].get("gnis_class")}
                                       for c in members]))

    # intakes: SDWIS (no coordinates) and the repository's local intake points
    for c in claims_by_source.get("epa_sdwis_intakes", []):
        features.append(_feature(f"INTAKE:SDWIS:{c['source_feature_id']}", "intake", [c], [],
                                 activity=c["attributes"].get("facility_activity_code"), located=False))
    for c in claims_by_source.get("repo_utility_assets", []):
        if c["feature_type"] == "intake":
            features.append(_feature(f"INTAKE:REPO:{c['source_feature_id']}", "intake", [c], [],
                                     located=c["lat"] is not None))

    # gauges: USGS monitoring locations that are not wells or springs, joined by NWS on the USGS id it publishes
    gauge_groups: dict[str, list[dict[str, Any]]] = {}
    for c in claims_by_source.get("usgs_monitoring_locations", []):
        if c["disposition"] == "RETAINED" and c["feature_type"] == "gauge":
            gauge_groups.setdefault(f"GAUGE:USGS:{c['source_feature_id']}", []).append(c)
    for c in claims_by_source.get("noaa_nwps_gauges", []):
        site = c["attributes"].get("usgs_site_no")
        gauge_groups.setdefault(f"GAUGE:USGS:{site}" if site else f"GAUGE:NWS:{c['source_feature_id']}", []).append(c)
    for key in sorted(gauge_groups):
        members = gauge_groups[key]
        usgs = next((c for c in members if c["source_key"] == "usgs_monitoring_locations"), None)
        ev = [{"tier": "I2", "key": f"USGS_SITE:{key.rsplit(':', 1)[1]}", "claim_ids": sorted(c["claim_id"] for c in members)}] \
            if len({c["source_key"] for c in members}) > 1 else []
        features.append(_feature(key, "gauge", members, ev, site_no=key.rsplit(":", 1)[1] if key.startswith("GAUGE:USGS:") else None,
                                 site_type_code=(usgs or {}).get("attributes", {}).get("site_type_code"),
                                 nws_lid=next((c["source_feature_id"] for c in members if c["source_key"] == "noaa_nwps_gauges"), None),
                                 located=any(c["lat"] is not None for c in members)))

    # repository OSM reservoirs: own features, candidate links to NHD reservoirs only
    for c in claims_by_source.get("repo_utility_assets", []):
        if c["feature_type"] == "reservoir":
            features.append(_feature(f"RESERVOIR:REPO:{c['source_feature_id']}", "reservoir", [c], [], located=c["lat"] is not None))

    for c in claims_by_source.get("usgs_wbd", []):
        a = c["attributes"]
        features.append(_feature(f"WATERSHED:{c['source_feature_id']}", "watershed", [c], [], level=a.get("level"),
                                 huc=a.get("huc"), areasqkm=a.get("areasqkm"), located=True))
    notes = {"nhd_gnis_ids_without_gnis_record": len(unmatched), "examples": unmatched[:10]}
    return features, links, conflicts, notes


def conflict(key: str, feature_ids: list[str], attribute: str, kind: str, values: list[dict[str, Any]],
             note: str | None = None, resolution: str = "UNRESOLVED_SHOWN") -> dict[str, Any]:
    return _clean({"conflict_id": "HYC_" + canonical_sha256(key)[:16], "feature_ids": sorted(feature_ids),
                   "attribute": attribute, "kind": kind, "values_by_claim": values, "resolution": resolution,
                   "note": note})


def link(link_type: str, source: str, target: str, edge_class: str, evidence: list[str],
         tier: str | None = None, **extra: Any) -> dict[str, Any]:
    return _clean({"link_id": "HYL_" + canonical_sha256([link_type, source, target])[:16], "link_type": link_type,
                   "from": source, "to": target, "edge_class": edge_class, "evidence_classes": evidence,
                   "identity_tier": tier,
                   "adjudication_state": "CANDIDATE_NOT_IDENTITY" if link_type == "CANDIDATE_SAME_FEATURE" else None,
                   **extra})


def well_aquifer_links(wells: list[dict[str, Any]], aquifers: list[dict[str, Any]],
                       polygon_index: PolygonIndex, link_type: str = "WELL_IN_AQUIFER"
                       ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ids = {f["feature_id"] for f in aquifers}
    links, crosstab, outside = [], {}, {"no_location": 0, "outside_all_polygons": 0, "in_non_aquifer_unit": 0}
    for w in wells:
        code, nat = w.get("aquifer_code"), w.get("national_aquifer_code")
        if code and aquifer_feature_id(f"USGS_AQFR:{code}") in ids:
            links.append(link(link_type, w["feature_id"], aquifer_feature_id(f"USGS_AQFR:{code}"),
                              "AUTHORITATIVE", ["USGS_AQUIFER_CODE"], basis=f"USGS aquifer_code {code}"))
        if nat and aquifer_feature_id(f"USGS_NAQFR:{nat}") in ids:
            links.append(link(link_type, w["feature_id"], aquifer_feature_id(f"USGS_NAQFR:{nat}"),
                              "AUTHORITATIVE", ["USGS_NATIONAL_AQUIFER_CODE"], basis=f"USGS national_aquifer_code {nat}"))
        if w["lat"] is None:
            outside["no_location"] += 1
            continue
        hits = polygon_index.containing(w["lon"], w["lat"])
        groups = sorted({h["group_key"] for h in hits if h.get("group_key")})
        if not hits:
            outside["outside_all_polygons"] += 1
        elif not groups:
            outside["in_non_aquifer_unit"] += 1
        for g in groups:
            links.append(link(link_type, w["feature_id"], aquifer_feature_id(g), "DERIVED_TOPOLOGICAL",
                              ["POINT_IN_MAPPED_POLYGON"],
                              basis="location inside the HA 730-N polygon; the map says nothing about depth"))
        if code:
            klass = ",".join(sorted({str(h.get("aq_code")) for h in hits})) or "none"
            crosstab.setdefault(code, {}).setdefault(klass, 0)
            crosstab[code][klass] += 1
    return links, {"aquifer_code_by_polygon_class": crosstab, "located_wells_without_polygon": outside}


def aquifer_links(claims: list[dict[str, Any]], aquifers: list[dict[str, Any]], wells: list[dict[str, Any]],
                  well_links: list[dict[str, Any]], equivalences: list[list[str]]) -> list[dict[str, Any]]:
    ids = {f["feature_id"] for f in aquifers}
    out = []
    co: dict[tuple[str, str], int] = {}
    for w in wells:
        if w.get("aquifer_code") and w.get("national_aquifer_code"):
            pair = (aquifer_feature_id(f"USGS_AQFR:{w['aquifer_code']}"),
                    aquifer_feature_id(f"USGS_NAQFR:{w['national_aquifer_code']}"))
            co[pair] = co.get(pair, 0) + 1
    for (local, national), n in sorted(co.items()):
        if local in ids and national in ids:
            out.append(link("AQUIFER_WITHIN", local, national, "AUTHORITATIVE", ["USGS_CO_ASSIGNED_ON_SITES"],
                            co_assigned_locations=n))
    for a, b in equivalences:
        fa, fb = aquifer_feature_id(a), aquifer_feature_id(b)
        if fa in ids and fb in ids:
            out.append(link("CANDIDATE_SAME_FEATURE", fa, fb, "CANDIDATE", ["ANALYST_NAME_EQUIVALENCE"], tier="I4"))
    by_well = {w["feature_id"]: w for w in wells}
    inside: dict[tuple[str, str], int] = {}
    for lk in well_links:
        if lk["edge_class"] != "DERIVED_TOPOLOGICAL":
            continue
        code = by_well[lk["from"]].get("aquifer_code")
        if code and aquifer_feature_id(f"USGS_AQFR:{code}") in ids:
            pair = (aquifer_feature_id(f"USGS_AQFR:{code}"), lk["to"])
            inside[pair] = inside.get(pair, 0) + 1
    for (code_feature, polygon_feature), n in sorted(inside.items()):
        out.append(link("CODED_WELLS_WITHIN_POLYGON", code_feature, polygon_feature, "DERIVED_TOPOLOGICAL",
                        ["CODED_WELLS_INSIDE"], wells=n))
    return out


def well_candidates(wells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Name+proximity (I4) and proximity-only (I5) candidates between wells from different sources.

    Municipio names are removed before names are compared: two wells in Guánica share that
    word and nothing else.
    """
    stop = frozenset(t for w in wells for t in normalize_name(w.get("municipio")).split())
    located = [w for w in wells if w["lat"] is not None]
    cells: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for w in located:
        cells.setdefault((int(w["lat"] / 0.002), int(w["lon"] / 0.002)), []).append(w)
    out = []
    for w in located:
        if not w["feature_id"].startswith("WELL:WQP:"):
            continue
        ci, cj = int(w["lat"] / 0.002), int(w["lon"] / 0.002)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for other in cells.get((ci + di, cj + dj), []):
                    if other is w:
                        continue
                    # two WQP organisations can publish the same well (PREQB_GW and its WQX copy);
                    # compare each such pair once, and never within one organisation
                    if other["feature_id"].startswith("WELL:WQP:") and (
                            _wqp_org(other) == _wqp_org(w) or other["feature_id"] < w["feature_id"]):
                        continue
                    d = haversine_m(w["lat"], w["lon"], other["lat"], other["lon"])
                    if d > WELL_PROXIMITY_M:
                        continue
                    named = any(names_compatible(a, b, stop) for a in well_names(w) for b in well_names(other))
                    out.append(link("CANDIDATE_SAME_FEATURE", w["feature_id"], other["feature_id"], "CANDIDATE",
                                    ["NORMALIZED_NAME", "PROXIMITY"] if named else ["PROXIMITY_ONLY"],
                                    tier="I4" if named else "I5", distance_m=round(d, 1)))
    return out


def _wqp_org(feature: Mapping[str, Any]) -> str:
    return feature["feature_id"].split(":", 2)[2].split("-", 1)[0]


def component_count(nodes: Iterable[str], links: Iterable[Mapping[str, Any]]) -> int:
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for lk in links:
        if lk["link_type"] == "CANDIDATE_SAME_FEATURE" and lk.get("identity_tier") == "I4" \
                and lk["from"] in parent and lk["to"] in parent:
            parent[find(lk["from"])] = find(lk["to"])
    return len({find(n) for n in parent})


def seeded_conflicts(claims_by_source_id: Mapping[str, dict[str, Any]], aquifers: list[dict[str, Any]],
                     datum: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    def ref(source_feature_id: str) -> dict[str, Any]:
        c = claims_by_source_id.get(source_feature_id)
        return {"claim_id": c["claim_id"], "source_key": c["source_key"]} if c else {"source_feature_id": source_feature_id}

    out = []
    south = [f["feature_id"] for f in aquifers if f["feature_id"] in (
        "AQ:HA730:114:main", "AQ:USGS_NAQFR:N300STHCST", "AQ:USGS_AQFR:110SCPL")]
    pira_south = [f["feature_id"] for f in aquifers if f["feature_id"].startswith("AQ:PIRA:SUR_")]
    if south and pira_south:
        out.append(conflict("south_coast_unit_count", south + pira_south, "south_coast_aquifer_units", "classification", [
            {**ref("HA730:114:main"), "value": "one 'South coast aquifer' (HA 730-N class 114)"},
            {**ref("USGS_NAQFR:N300STHCST"), "value": "one national aquifer 'South Coast aquifer (Puerto Rico)'"},
            {**ref("PIRA:SUR_PATILLAS_ARROYO"),
             "value": "independent valley aquifers: 'No existe lo que comúnmente se refiere como el \"Gran Acuífero del Sur\". "
                      "Cada valle aluvial forma un acuífero independiente' (PIRA 2016, PDF p. 113)"}]))
    culebra = [f["feature_id"] for f in aquifers if f.get("island") == "culebra"]
    mona = [f["feature_id"] for f in aquifers if f["feature_id"] in ("AQ:USGS_AQFR:122ISLM", "AQ:USGS_AQFR:122LIRO")]
    if culebra or mona:
        out.append(conflict("culebra_mona_existence", culebra + mona, "aquifer_existence", "existence", [
            {"source_key": "usgs_ha730_text", "value": "'the islands of Mona and Culebra lack any significant aquifers' "
                                                        "(HA 730-N, N-PR_VItext1.html)"},
            {"source_key": "usgs_ha730_aquifers_pr", "value": f"{len(culebra)} aquifer group(s) mapped on Culebra in the same release"},
            {"source_key": "usgs_aquifer_codes", "value": "USGS aquifer codes 122ISLM (Isla Mona Dolomite) and 122LIRO "
                                                          "(Lirio Limestone) name Mona Island units"}]))
    ncl = [f for f in aquifers if f["feature_id"] in ("AQ:HA730:4191:main", "AQ:HA730:4192:main")]
    if ncl:
        mapped_mi2 = round(sum(f.get("area_km2") or 0 for f in ncl) / 2.589988, 0)
        out.append(conflict("ncl_area", [f["feature_id"] for f in ncl] + ["AQ:PIRA:NCL_SUPERIOR"], "north_coast_area",
                            "extent", [
            {"source_key": "usgs_ha730_text", "value": "nearly 700 square miles (HA 730-N, N-PR_VItext4.html)"},
            {**ref("PIRA:NCL_SUPERIOR"), "value": "about 905 mi² for the Costa Norte aquifers (PIRA 2016, PDF p. 108)"},
            {"source_key": "usgs_ha730_aquifers_pr", "value": f"{mapped_mi2:.0f} mi² mapped for classes 4191+4192 on the "
                                                              "main island (computed by this inventory from the polygons)"}],
            note="The three figures need not describe the same extent: the computed area excludes the confining unit."))
    if datum:
        checks = datum.get("checks", {})
        out.append(conflict("ha730_datum", [f["feature_id"] for f in aquifers if f["feature_id"].startswith("AQ:HA730:")],
                            "horizontal_datum", "attribute", [
            {"source_key": "usgs_ha730_aquifers_pr", "value": "NAD27 declared in the .prj",
             "coastline_median_m": checks.get("declared_nad27", {}).get("median_m"),
             "north_offset_m": checks.get("declared_nad27", {}).get("median_north_offset_m")},
            {"source_key": "usgs_ha730_aquifers_pr", "value": "Puerto Rico 1940 (EPSG:4139), inferred from fit",
             "coastline_median_m": checks.get("puerto_rico_1940", {}).get("median_m"),
             "north_offset_m": checks.get("puerto_rico_1940", {}).get("median_north_offset_m")}],
            resolution="RESOLVED_BY_MEASURED_FIT",
            note="Geometry is drawn with Puerto Rico 1940 because it fits the Census coastline; the declared datum "
                 "puts the island about 200 m north."))
    return out


def surface_links(features: list[dict[str, Any]], waterbody_geojson: Mapping[str, Any],
                  watershed_geojson: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Watershed attribution, gauges on waterbodies, and OSM-reservoir candidates. Location only."""
    by_id = {f["feature_id"]: f for f in features}
    wb_index = PolygonIndex(waterbody_geojson.get("features", []))
    huc10 = PolygonIndex(x for x in watershed_geojson.get("features", []) if (x.get("properties") or {}).get("level") == "huc10")
    links, counts = [], {"with_huc10": 0, "gauges_on_waterbodies": 0, "osm_reservoir_candidates": 0}
    polygon_feature = {}
    for f in features:
        if f["feature_type"] in ("waterbody", "reservoir") and f.get("nhd_polygons"):
            polygon_feature.update({pid: f["feature_id"] for pid in f.get("_nhd_ids", [])})
    for f in features:
        if f["lat"] is None or f["feature_type"] in ("stream", "watershed", "aquifer"):
            continue
        sheds = [h.get("id") for h in huc10.containing(f["lon"], f["lat"])]
        if sheds:
            f["huc10"] = sheds[0].split(":", 1)[1]
            counts["with_huc10"] += 1
        if f["feature_type"] == "gauge" and f.get("site_type_code") == "LK" or f["feature_id"].startswith("RESERVOIR:REPO:"):
            for hit in wb_index.containing(f["lon"], f["lat"]):
                target = polygon_feature.get(str(hit.get("id")))
                if not target or target == f["feature_id"]:
                    continue
                if f["feature_type"] == "gauge":
                    links.append(link("GAUGE_ON_WATERBODY", f["feature_id"], target, "DERIVED_TOPOLOGICAL",
                                      ["POINT_IN_MAPPED_POLYGON"]))
                    counts["gauges_on_waterbodies"] += 1
                else:
                    named = names_compatible(f["display_name"], by_id[target]["display_name"])
                    links.append(link("CANDIDATE_SAME_FEATURE", f["feature_id"], target, "CANDIDATE",
                                      ["NORMALIZED_NAME", "INSIDE_MAPPED_POLYGON"] if named else ["INSIDE_MAPPED_POLYGON"],
                                      tier="I4" if named else "I5"))
                    counts["osm_reservoir_candidates"] += 1
    return links, counts


def build_inventory(*, claims: list[dict[str, Any]], aquifer_geojson: Mapping[str, Any],
                    asset_ids_by_site: Mapping[str, list[str]], equivalences: list[list[str]],
                    stage_receipts: Mapping[str, Any], now: str,
                    waterbody_geojson: Mapping[str, Any] | None = None,
                    watershed_geojson: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Every output of the inventory from its claims. Pure and deterministic."""
    by_source: dict[str, list[dict[str, Any]]] = {}
    for c in claims:
        by_source.setdefault(c["source_key"], []).append(c)
    aquifer_claims = [c for c in claims if c["feature_type"] == "aquifer"]
    aquifers = build_aquifers(aquifer_claims)
    wells, coord_conflicts = build_wells(by_source.get("usgs_monitoring_locations", []), by_source.get("wqp_wells", []),
                                         by_source.get("epa_sdwis_wells", []), asset_ids_by_site)
    index = PolygonIndex(f for f in aquifer_geojson.get("features", [])
                         if (f.get("properties") or {}).get("disposition") == "RETAINED"
                         or (f.get("properties") or {}).get("exclusion_reason", "").startswith(("confining", "'other'")))
    springs = build_springs(by_source.get("usgs_monitoring_locations", []), by_source.get("wqp_springs", []),
                            by_source.get("usgs_gnis_names", []))
    wl, spatial = well_aquifer_links(wells, aquifers, index)
    sl, spring_spatial = well_aquifer_links(springs, aquifers, index, "SPRING_IN_AQUIFER")
    spatial["springs"] = spring_spatial
    al = aquifer_links(aquifer_claims, aquifers, wells, wl, equivalences)
    wc = well_candidates(wells)
    sc = point_candidates(springs)
    surface, surf_links, surf_conflicts, surface_notes = build_surface(by_source)
    for f in surface:
        if f["feature_type"] in ("waterbody", "reservoir") and f.get("nhd_polygons"):
            f["_nhd_ids"] = [c["source_feature_id"] for c in by_source.get("usgs_nhd_waterbodies", [])
                             if c["claim_id"] in set(f["claim_ids"])]
    loc_links, loc_counts = surface_links(wells + springs + surface, waterbody_geojson or {}, watershed_geojson or {})
    for f in surface:
        f.pop("_nhd_ids", None)
    links = sorted(wl + sl + al + wc + sc + surf_links + loc_links, key=lambda x: x["link_id"])
    ids = [x["link_id"] for x in links]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate link ids")
    claims_by_sfid = {c["source_feature_id"]: c for c in aquifer_claims}
    conflicts = sorted(seeded_conflicts(claims_by_sfid, aquifers, (stage_receipts.get("aquifers") or {}).get("datum"))
                       + coord_conflicts + surf_conflicts, key=lambda x: x["conflict_id"])

    features = aquifers + wells + springs + surface
    assigned = {cid for f in features for cid in f["claim_ids"]}
    retained = {c["claim_id"] for c in claims if c["disposition"] == "RETAINED" and c["feature_type"] in PHASE_ENUMERATED}
    if retained - assigned:
        raise ValueError(f"{len(retained - assigned)} retained claims were not assigned to a feature")
    members: dict[str, dict[str, int]] = {}
    for lk in wl:
        m = members.setdefault(lk["to"], {"AUTHORITATIVE": 0, "DERIVED_TOPOLOGICAL": 0})
        m[lk["edge_class"]] += 1
    spring_members: dict[str, int] = {}
    for lk in sl:
        spring_members[lk["to"]] = spring_members.get(lk["to"], 0) + 1
    for f in aquifers:
        f["member_wells"] = members.get(f["feature_id"], {"AUTHORITATIVE": 0, "DERIVED_TOPOLOGICAL": 0})
        if spring_members.get(f["feature_id"]):
            f["member_springs"] = spring_members[f["feature_id"]]

    def type_summary(kind: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        nodes = [f["feature_id"] for f in items]
        out = {"features_upper": len(items), "features_lower": component_count(nodes, links),
               "candidate_links_i4": sum(1 for x in links if x["link_type"] == "CANDIDATE_SAME_FEATURE"
                                         and x.get("identity_tier") == "I4" and x["from"] in set(nodes)),
               "candidate_links_i5": sum(1 for x in links if x["link_type"] == "CANDIDATE_SAME_FEATURE"
                                         and x.get("identity_tier") == "I5" and x["from"] in set(nodes)),
               "by_source_combination": {}}
        for f in items:
            combo = "+".join(f["sources"])
            out["by_source_combination"][combo] = out["by_source_combination"].get(combo, 0) + 1
        if kind not in ("aquifer", "well", "spring", "watershed"):
            out["located"] = sum(1 for f in items if f.get("located"))
            out["unlocated"] = len(items) - out["located"]
        if kind in ("well", "spring"):
            own = wl if kind == "well" else sl
            out["located"] = sum(1 for f in items if f["located"])
            out["unlocated"] = sum(1 for f in items if not f["located"])
            out["with_usgs_aquifer_code"] = sum(1 for f in items if f.get("aquifer_code"))
            out["bound_authoritative"] = len({x["from"] for x in own if x["edge_class"] == "AUTHORITATIVE"})
            out["bound_by_polygon_only"] = len({x["from"] for x in own if x["edge_class"] == "DERIVED_TOPOLOGICAL"}
                                               - {x["from"] for x in own if x["edge_class"] == "AUTHORITATIVE"})
        if kind == "aquifer":
            out["by_authority"] = {}
            for f in items:
                out["by_authority"][f["authority"]] = out["by_authority"].get(f["authority"], 0) + 1
        return out

    source_ledgers = {}
    for key, rows in sorted(by_source.items()):
        excluded: dict[str, int] = {}
        out_of_phase = 0
        for c in rows:
            if c["disposition"] == "EXCLUDED":
                excluded[c["exclusion_reason"]] = excluded.get(c["exclusion_reason"], 0) + 1
            elif c["claim_id"] not in assigned:
                out_of_phase += 1
        if out_of_phase:
            excluded["feature type not enumerated in this phase"] = out_of_phase
        ledger = close_ledger(source_rows=len(rows), retained=len(rows) - sum(excluded.values()),
                              excluded=excluded, unresolved=0)
        ledger["assigned_to_features"] = sum(1 for c in rows if c["claim_id"] in assigned)
        source_ledgers[key] = ledger
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "generated_at": now,
        "phase_scope": {"feature_types_enumerated": list(PHASE_ENUMERATED),
                        "feature_types_not_enumerated": [t for t in FEATURE_TYPES if t not in PHASE_ENUMERATED]},
        "completeness_claimed": False,
        "denominator_definition": "the union of the enumerated sources; every retained claim is assigned to exactly "
                                  "one feature and every excluded claim carries a reason",
        "coverage": {t: type_summary(t, [f for f in features if f["feature_type"] == t]) for t in FEATURE_TYPES},
        "source_ledgers": source_ledgers,
        "spatial": spatial,
        "surface": {**surface_notes, **loc_counts},
        "conflicts": len(conflicts),
        "stage_receipts": {k: {kk: vv for kk, vv in v.items() if kk != "manifestations"}
                           for k, v in stage_receipts.items()},
        "manifestations": [m for v in stage_receipts.values() for m in v.get("manifestations", [])],
        "open_residue": [
            "PRASA production wells: EPA SDWIS lists them without coordinates, so they are not placed or bound to an aquifer",
            "DRNA water-franchise registry of permitted wells: no public registry found",
            "DRNA and Junta de Planificación aquifer layers: sige.pr.gov and gis.otg.pr.gov unreachable from the build environment",
            "names of the HA 730-N alluvial-valley polygons: the release labels them only by class",
            "springs known only from speleological or local records: GNIS names 2 springs in Puerto Rico and USGS "
            "monitors 221; no public spring registry was found",
            "PRASA intakes: EPA SDWIS lists 690 intake facilities without coordinates; they are listed, not placed",
            "stream gauges are attributed to watersheds by location; their reach on the stream network is not "
            "computed (that needs network navigation, not distance)",
            "DRNA reservoir and embalse lists: sige.pr.gov unreachable from the build environment",
        ],
    }
    return {"features": features, "links": links, "conflicts": conflicts, "receipt": receipt}


# ── read side ─────────────────────────────────────────────────────────────────
class InventoryStore:
    """Committed inventory files, re-read only when they change on disk."""

    def __init__(self) -> None:
        self._key: tuple[Any, ...] | None = None
        self._data: dict[str, Any] = {}
        self._state_key: tuple[Any, ...] | None = None
        self._last_obs: dict[str, str] | None = None

    def load(self, data_dir: Path) -> dict[str, Any]:
        hydro = data_dir / HYDRO_DIR
        feature_paths = sorted(hydro.glob(FEATURES_FILE.format("*")))
        paths = [*feature_paths, hydro / LINKS_FILE, hydro / CONFLICTS_FILE, hydro / RECEIPT_FILE]
        key = tuple((str(p), p.stat().st_mtime_ns if p.is_file() else None) for p in paths)
        if key != self._key:
            receipt_path = hydro / RECEIPT_FILE
            features = [f for p in feature_paths for f in read_jsonl(p)]
            links = read_jsonl(hydro / LINKS_FILE)
            self._data = {
                "features": features, "by_id": {f["feature_id"]: f for f in features}, "links": links,
                "conflicts": read_jsonl(hydro / CONFLICTS_FILE),
                "receipt": json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.is_file() else None,
                "links_by_feature": _index_links(links),
            }
            self._key = key
        return self._data

    def last_observations(self, data_dir: Path) -> dict[str, str] | None:
        """``{site_no: latest observed_date}`` across the reading files, or None if none exist."""
        paths = [data_dir / name for name in READING_FILES]
        key = tuple((str(p), p.stat().st_mtime_ns if p.is_file() else None) for p in paths)
        if key == self._state_key:
            return self._last_obs
        if not any(p.is_file() for p in paths):
            self._last_obs = None
        else:
            latest: dict[str, str] = {}
            for p in paths:
                if not p.is_file():
                    continue
                with p.open(encoding="utf-8") as handle:
                    for line in handle:
                        if '"groundwater_level"' not in line:
                            continue
                        row = json.loads(line)
                        site, day = str(row.get("site_no") or ""), str(row.get("observed_date") or "")[:10]
                        if site and day and day > latest.get(site, ""):
                            latest[site] = day
            self._last_obs = latest
        self._state_key = key
        return self._last_obs


def _index_links(links: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    idx: dict[str, list[dict[str, Any]]] = {}
    for lk in links:
        idx.setdefault(lk["from"], []).append(lk)
        idx.setdefault(lk["to"], []).append(lk)
    return idx


def monitoring_state(feature: Mapping[str, Any], last_obs: Mapping[str, str] | None, today: date) -> dict[str, Any]:
    if feature.get("feature_type") != "well":
        return {"state": None, "last_observed_date": None}
    if last_obs is None:
        return {"state": "READINGS_ABSENT_ON_SERVER", "last_observed_date": None}
    day = last_obs.get(str(feature.get("site_no") or ""))
    if not day:
        return {"state": "NO_DATA", "last_observed_date": None}
    try:
        age = (today - datetime.strptime(day, "%Y-%m-%d").date()).days
    except ValueError:
        return {"state": "NO_DATA", "last_observed_date": None}
    return {"state": "MONITORED_NOW" if age <= MONITORED_NOW_DAYS else "HISTORICAL_ONLY", "last_observed_date": day}


def wells_in_aquifer(data: Mapping[str, Any], aquifer_id: str, include_polygon: bool) -> list[str]:
    classes = {"AUTHORITATIVE", "DERIVED_TOPOLOGICAL"} if include_polygon else {"AUTHORITATIVE"}
    return sorted({lk["from"] for lk in data["links_by_feature"].get(aquifer_id, [])
                   if lk["link_type"] == "WELL_IN_AQUIFER" and lk["to"] == aquifer_id and lk["edge_class"] in classes})


__all__ = [
    "AQUIFER_GEOJSON", "CLAIMS_FORMAT", "CONFLICTS_FILE", "FEATURES_FILE", "FEATURE_TYPES", "GW_SITE_TYPES", "HYDRO_DIR",
    "LINKS_FILE", "MONITORED_NOW_DAYS", "MONITORING_STATES", "PHASE_ENUMERATED", "RECEIPT_FILE", "RECEIPT_SCHEMA",
    "SOURCES_CONFIG", "WELL_PROXIMITY_M",
    "InventoryStore", "PolygonIndex",
    "aquifer_feature_id", "aquifer_links", "atomic_write", "build_aquifers", "build_inventory", "build_springs",
    "build_surface", "build_wells", "point_candidates", "surface_links", "canonical_sha256",
    "claim", "close_ledger", "component_count", "conflict", "haversine_m", "link", "monitoring_state",
    "name_tokens", "names_compatible", "well_names", "normalize_name", "read_claims", "read_jsonl", "seeded_conflicts", "well_aquifer_links",
    "well_candidates", "wells_in_aquifer", "write_claims", "write_fail_receipt", "write_jsonl",
]
