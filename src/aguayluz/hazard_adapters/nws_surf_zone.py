"""NWS San Juan Surf Zone Forecast (SRF) adapter for the outdoor-conditions layer.

The SRF is a fixed-format text product WFO San Juan (TJSJ) issues about twice a day
(``FZCA52 TJSJ``). Each ``$$``-terminated segment covers one land forecast zone and
names the beaches it applies to::

    PRZ001-182200-
    San Juan and Vicinity PR-
    Including the beaches of Carolina, San Juan and Toa Baja
    330 AM AST Sun Oct 18 2026

    .TODAY...
    Rip Current Risk*...........Moderate.
    Surf Height.................Around 4 feet.
    ...
    .TUESDAY...Surf height around 7 feet. Partly sunny. ...

Detailed periods (``.TODAY``, then the next day) carry a rip current risk category; the
one-line extended periods carry surf height only.

Binding is the product's own text: the municipios named in "Including the beaches of"
(``AUTHORITATIVE_BINDING``, method ``srf.including_beaches``). Island segments without
that line (Culebra, Vieques) bind by the zone name (``srf.zone_name``). A coastal
municipio the product never names is *not covered* — it is not assumed to share a
neighbour's risk. U.S. Virgin Islands segments (``VIZ``) are excluded and counted.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus

SOURCE_AUTHORITY = "NOAA/NWS Weather Forecast Office San Juan"
CANONICAL_PREFIX = "NWS_SRF:"
HAZARD_TYPE = "RIP_CURRENT_RISK"
ISSUING_OFFICE = "TJSJ"

#: Puerto Rico observes Atlantic Standard Time all year.
AST = timezone(timedelta(hours=-4))

#: Rip current risk categories in rising order (NWS national categories).
RISK_LEVELS: tuple[str, ...] = ("LOW", "MODERATE", "HIGH")

_TODAY_LABELS = {"TODAY", "TONIGHT", "THIS AFTERNOON", "REST OF TODAY", "THIS MORNING"}
_WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")

_UGC_RE = re.compile(r"^(?P<body>[A-Z]{2}[CZ]\d{3}[0-9A-Z>\-]*?)-(?P<expires>\d{6})-\s*$")
_PERIOD_RE = re.compile(r"^\.(?P<label>[A-Z][A-Z ]*?)\.\.\.(?P<rest>.*)$")
_FIELD_RE = re.compile(r"^(?P<name>[A-Z][A-Za-z ]+?)\*?\.{3,}(?P<value>.*)$")
_ISSUED_LINE_RE = re.compile(r"^\d{3,4} (AM|PM) [A-Z]{3} ")
_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*to\s*(\d+(?:\.\d+)?)\s*(?:feet|ft)", re.I)
_AROUND_RE = re.compile(r"(?:around|near|up to)?\s*(\d+(?:\.\d+)?)\s*(?:feet|ft)", re.I)


@dataclass
class Period:
    label: str
    detailed: bool
    rip_current_risk_raw: str | None = None
    surf_height_text: str | None = None
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def rip_current_risk(self) -> str | None:
        raw = (self.rip_current_risk_raw or "").strip().rstrip(".").upper()
        return raw if raw in RISK_LEVELS else None


@dataclass
class Segment:
    ugc: str
    zones: list[str]
    expires: str
    name: str
    beaches: list[str] | None
    periods: list[Period]

    @property
    def is_usvi(self) -> bool:
        return all(z.startswith("VI") for z in self.zones)

    @property
    def is_pr(self) -> bool:
        return any(z.startswith("PR") for z in self.zones)


def parse_ugc(line: str) -> tuple[list[str], str] | None:
    """``PRZ001-005>007-182200-`` -> (["PRZ001", "PRZ005", "PRZ006", "PRZ007"], "182200")."""
    match = _UGC_RE.match(line.strip())
    if not match:
        return None
    zones: list[str] = []
    prefix = ""
    for token in match.group("body").split("-"):
        if not token:
            continue
        head = re.match(r"^([A-Z]{2}[CZ])(.*)$", token)
        if head:
            prefix, token = head.group(1), head.group(2)
        if not prefix:
            return None
        if ">" in token:
            lo, hi = token.split(">", 1)
            if not (lo.isdigit() and hi.isdigit()) or int(hi) < int(lo):
                return None
            zones.extend(f"{prefix}{n:03d}" for n in range(int(lo), int(hi) + 1))
        elif token.isdigit():
            zones.append(f"{prefix}{int(token):03d}")
        else:
            return None
    return (zones, match.group("expires")) if zones else None


def _split_names(text: str) -> list[str]:
    text = " ".join(text.split())
    parts = re.split(r",\s*|\s+and\s+", text)
    return [p.strip() for p in parts if p.strip()]


def parse_product(text: str) -> list[Segment]:
    """Every UGC segment in an SRF product, in product order."""
    segments: list[Segment] = []
    for chunk in text.split("$$"):
        lines = [ln.rstrip() for ln in chunk.splitlines()]
        start = next((i for i, ln in enumerate(lines) if parse_ugc(ln)), None)
        if start is None:
            continue
        zones, expires = parse_ugc(lines[start])  # type: ignore[misc]
        body = lines[start + 1:]
        # Zone name: the line(s) ending in "-" right after the UGC line.
        name_lines: list[str] = []
        idx = 0
        while idx < len(body) and body[idx].strip().endswith("-"):
            name_lines.append(body[idx].strip().rstrip("-").strip())
            idx += 1
        name = " ".join(name_lines)
        beaches: list[str] | None = None
        if idx < len(body) and body[idx].strip().startswith("Including the beaches of"):
            text_lines = [body[idx].strip()[len("Including the beaches of"):]]
            idx += 1
            while idx < len(body) and body[idx].strip() and not _ISSUED_LINE_RE.match(body[idx].strip()):
                text_lines.append(body[idx].strip())
                idx += 1
            beaches = _split_names(" ".join(text_lines))
        segments.append(Segment(
            ugc=lines[start].strip(), zones=zones, expires=expires, name=name,
            beaches=beaches, periods=_parse_periods(body[idx:]),
        ))
    return segments


def _parse_periods(lines: list[str]) -> list[Period]:
    periods: list[Period] = []
    current: Period | None = None
    last_field: str | None = None
    for raw in lines:
        line = raw.strip()
        if line.startswith("&&"):
            break
        match = _PERIOD_RE.match(line)
        if match:
            rest = match.group("rest").strip()
            current = Period(label=match.group("label").strip(), detailed=not rest)
            if rest:
                current.surf_height_text = rest
            periods.append(current)
            last_field = None
            continue
        if current is None or not line:
            last_field = None if not line else last_field
            continue
        if not current.detailed:
            # Extended period wrapped onto the next line.
            current.surf_height_text = f"{current.surf_height_text} {line}".strip()
            continue
        field_match = _FIELD_RE.match(line)
        if field_match:
            key = field_match.group("name").strip()
            current.fields[key] = field_match.group("value").strip()
            last_field = key
        elif last_field and raw.startswith(" "):
            current.fields[last_field] = f"{current.fields[last_field]} {line}".strip()
    for period in periods:
        if period.detailed:
            period.rip_current_risk_raw = period.fields.get("Rip Current Risk")
            period.surf_height_text = period.fields.get("Surf Height")
    return periods


def surf_height_ft(text: str | None) -> tuple[float | None, float | None]:
    """(min, max) feet from "Around 4 feet", "3 to 5 feet", "Surf height around 7 feet."."""
    if not text:
        return None, None
    span = _RANGE_RE.search(text)
    if span:
        return float(span.group(1)), float(span.group(2))
    single = _AROUND_RE.search(text)
    if single:
        value = float(single.group(1))
        return value, value
    return None, None


def period_dates(labels: list[str], issued_local: date) -> list[date | None]:
    """Calendar date of each period label, walking forward from the issuance date."""
    out: list[date | None] = []
    cursor = issued_local
    for label in labels:
        upper = label.upper()
        if upper in _TODAY_LABELS:
            out.append(issued_local)
            cursor = issued_local + timedelta(days=1)
            continue
        weekday = next((i for i, d in enumerate(_WEEKDAYS) if upper.startswith(d)), None)
        if weekday is None:
            out.append(None)
            continue
        day = cursor
        while day.weekday() != weekday:
            day += timedelta(days=1)
        out.append(day)
        cursor = day + timedelta(days=1)
    return out


def material_state(zone: str, day: date, period: Period) -> dict[str, Any]:
    lo, hi = surf_height_ft(period.surf_height_text)
    return {
        "zone": zone,
        "date": day.isoformat(),
        "rip_current_risk": period.rip_current_risk,
        "surf_min_ft": lo,
        "surf_max_ft": hi,
    }


def material_digest(material: dict[str, Any]) -> str:
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def canonical_event_id(zone: str, day: date) -> str:
    return f"{CANONICAL_PREFIX}{zone}:{day.isoformat()}"


def stable_record_id(material: dict[str, Any], supersedes_record_id: str | None) -> str:
    chained = sha256(
        f"{material_digest(material)}|{supersedes_record_id or 'HEAD'}".encode()
    ).hexdigest()
    event = f"{CANONICAL_PREFIX}{material['zone']}:{material['date']}"
    return f"{event}:REV:{chained[:20]}"


def normalize(
    segment: Segment,
    zone: str,
    day: date,
    period: Period,
    manifestation_id: str,
    *,
    issued_at: datetime,
    product_id: str,
    municipality_id: str | None,
    supersedes_record_id: str | None,
    municipios: list[str] | None = None,
) -> HazardRecord:
    """One zone-day rip current forecast as a HYDROMETEOROLOGY advisory record.

    ``municipios`` are the Census names the segment bound to (the same bindings the
    ingest writes as relationships), carried so the alert promoter needs no join.
    """
    material = material_state(zone, day, period)
    start = datetime(day.year, day.month, day.day, tzinfo=AST)
    risk = period.rip_current_risk
    return HazardRecord(
        record_id=stable_record_id(material, supersedes_record_id),
        canonical_event_id=canonical_event_id(zone, day),
        record_kind=RecordKind.ADVISORY,
        family=HazardFamily.HYDROMETEOROLOGY,
        hazard_type=HAZARD_TYPE,
        source_authority=SOURCE_AUTHORITY,
        source_record_id=f"{product_id}:{zone}:{period.label}",
        manifestation_id=manifestation_id,
        title_raw=f"{segment.name or zone} — {period.label.title()}",
        description_raw=period.surf_height_text,
        normalized_label=(f"Rip current risk {risk.title()} — {segment.name or zone}"
                          if risk else f"Surf forecast — {segment.name or zone}"),
        status=RecordStatus.PROVISIONAL if risk else RecordStatus.UNRESOLVED,
        issued_at=issued_at,
        effective_from=start,
        effective_to=start + timedelta(days=1),
        municipality_id=municipality_id,
        geography_basis="NWS_SRF_ZONE:AUTHORITATIVE_BINDING",
        geometry_precision="REPRESENTATIVE_POINT",
        provisional=True,
        supersedes_record_id=supersedes_record_id,
        raw_attributes={
            "ugc": segment.ugc,
            "zone_name": segment.name,
            "beaches": segment.beaches,
            "period_label": period.label,
            "fields": period.fields or None,
            "surf_height_text": period.surf_height_text,
        },
        normalized_values={
            **material,
            "rip_current_risk_raw": period.rip_current_risk_raw,
            "municipios": sorted(municipios or []),
            "material_digest": material_digest(material),
        },
    )


__all__ = [
    "AST",
    "CANONICAL_PREFIX",
    "HAZARD_TYPE",
    "ISSUING_OFFICE",
    "RISK_LEVELS",
    "SOURCE_AUTHORITY",
    "Period",
    "Segment",
    "canonical_event_id",
    "material_digest",
    "material_state",
    "normalize",
    "parse_product",
    "parse_ugc",
    "period_dates",
    "stable_record_id",
    "surf_height_ft",
]
