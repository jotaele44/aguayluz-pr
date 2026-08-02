"""Research-only site, survey, and fruiting lifecycle foundation."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

LifecycleState = Literal[
    "dormant_or_unknown",
    "environmental_priming",
    "emergence_suspected",
    "fruiting_confirmed",
    "expansion",
    "peak",
    "senescence",
    "decomposition",
    "post_fruiting",
]
Confidence = Literal["low", "medium", "high", "verified"]

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "dormant_or_unknown": frozenset({"environmental_priming", "emergence_suspected", "fruiting_confirmed"}),
    "environmental_priming": frozenset({"dormant_or_unknown", "emergence_suspected", "fruiting_confirmed"}),
    "emergence_suspected": frozenset({"dormant_or_unknown", "fruiting_confirmed"}),
    "fruiting_confirmed": frozenset({"expansion", "peak", "senescence", "decomposition"}),
    "expansion": frozenset({"peak", "senescence", "decomposition"}),
    "peak": frozenset({"senescence", "decomposition"}),
    "senescence": frozenset({"decomposition", "post_fruiting"}),
    "decomposition": frozenset({"post_fruiting"}),
    "post_fruiting": frozenset({"dormant_or_unknown", "environmental_priming", "emergence_suspected", "fruiting_confirmed"}),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MushroomSite:
    site_id: str
    name: str
    municipality: str | None
    latitude: float | None
    longitude: float | None
    coordinate_confidence: str
    sensitive: bool = False
    habitat: str | None = None
    substrate: str | None = None
    host_taxon: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence_refs"] = sorted(set(self.evidence_refs))
        return value


@dataclass(frozen=True)
class SurveySession:
    survey_id: str
    site_id: str
    started_at: str
    ended_at: str | None
    observer: str
    method: str
    effort_minutes: float
    area_m2: float | None
    detection_status: Literal["detected", "not_detected", "not_assessed"]
    notes: str | None = None


@dataclass(frozen=True)
class LifecycleObservation:
    observation_id: str
    survey_id: str
    site_id: str
    observed_at: str
    lifecycle_state: LifecycleState
    confidence: Confidence
    taxon_name: str | None = None
    count: int | None = None
    occupied_area_m2: float | None = None
    development_stage: str | None = None
    condition: str | None = None
    substrate: str | None = None
    host_taxon: str | None = None
    media_ids: tuple[str, ...] = field(default_factory=tuple)
    notes: str | None = None


@dataclass(frozen=True)
class MediaEvidence:
    media_id: str
    observation_id: str
    media_type: Literal["photo", "video", "audio", "document"]
    sha256: str
    captured_at: str | None
    source_uri: str | None = None
    caption: str | None = None


@dataclass(frozen=True)
class EnvironmentalSnapshot:
    snapshot_id: str
    site_id: str
    observed_at: str
    source_id: str
    rainfall_24h_mm: float | None = None
    rainfall_72h_mm: float | None = None
    temperature_c: float | None = None
    relative_humidity_pct: float | None = None
    soil_moisture_pct: float | None = None
    canopy_pct: float | None = None
    wind_kph: float | None = None
    raw_payload_sha256: str | None = None


@dataclass(frozen=True)
class StateTransition:
    transition_id: str
    site_id: str
    from_state: LifecycleState
    to_state: LifecycleState
    effective_at: str
    evidence_observation_id: str
    confidence: Confidence
    reason: str


LIFECYCLE_DDL = """
CREATE TABLE IF NOT EXISTS mushroom_sites (
 site_id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, payload_json TEXT NOT NULL, appended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS survey_sessions (
 survey_id TEXT PRIMARY KEY, site_id TEXT NOT NULL REFERENCES mushroom_sites(site_id), payload_json TEXT NOT NULL, appended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lifecycle_observations (
 observation_id TEXT PRIMARY KEY, survey_id TEXT NOT NULL REFERENCES survey_sessions(survey_id), site_id TEXT NOT NULL REFERENCES mushroom_sites(site_id), lifecycle_state TEXT NOT NULL, payload_json TEXT NOT NULL, appended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_evidence (
 media_id TEXT PRIMARY KEY, observation_id TEXT NOT NULL REFERENCES lifecycle_observations(observation_id), sha256 TEXT NOT NULL, payload_json TEXT NOT NULL, appended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS environmental_snapshots (
 snapshot_id TEXT PRIMARY KEY, site_id TEXT NOT NULL REFERENCES mushroom_sites(site_id), payload_json TEXT NOT NULL, appended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lifecycle_transitions (
 transition_id TEXT PRIMARY KEY, site_id TEXT NOT NULL REFERENCES mushroom_sites(site_id), from_state TEXT NOT NULL, to_state TEXT NOT NULL, evidence_observation_id TEXT NOT NULL REFERENCES lifecycle_observations(observation_id), payload_json TEXT NOT NULL, appended_at TEXT NOT NULL
);
"""


def initialize_lifecycle_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(LIFECYCLE_DDL)
    conn.commit()


def _append(conn: sqlite3.Connection, table: str, id_column: str, record_id: str, payload: dict[str, Any], now: str, extras: tuple[Any, ...] = ()) -> None:
    columns = [id_column]
    values: list[Any] = [record_id]
    if table == "mushroom_sites":
        columns.append("fingerprint")
        values.append(digest(payload))
    elif table == "survey_sessions":
        columns.append("site_id")
        values.append(payload["site_id"])
    elif table == "lifecycle_observations":
        columns.extend(["survey_id", "site_id", "lifecycle_state"])
        values.extend([payload["survey_id"], payload["site_id"], payload["lifecycle_state"]])
    elif table == "media_evidence":
        columns.extend(["observation_id", "sha256"])
        values.extend([payload["observation_id"], payload["sha256"]])
    elif table == "environmental_snapshots":
        columns.append("site_id")
        values.append(payload["site_id"])
    elif table == "lifecycle_transitions":
        columns.extend(["site_id", "from_state", "to_state", "evidence_observation_id"])
        values.extend([payload["site_id"], payload["from_state"], payload["to_state"], payload["evidence_observation_id"]])
    columns.extend(["payload_json", "appended_at"])
    values.extend([canonical_json(payload), now])
    placeholders = ",".join("?" for _ in values)
    conn.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})", tuple(values) + extras)
    conn.commit()


def append_site(conn: sqlite3.Connection, site: MushroomSite, now: str) -> None:
    if (site.latitude is None) != (site.longitude is None):
        raise ValueError("incomplete_coordinates")
    if site.latitude is not None and not -90 <= site.latitude <= 90:
        raise ValueError("latitude_out_of_range")
    if site.longitude is not None and not -180 <= site.longitude <= 180:
        raise ValueError("longitude_out_of_range")
    _append(conn, "mushroom_sites", "site_id", site.site_id, site.payload(), now)


def append_survey(conn: sqlite3.Connection, survey: SurveySession, now: str) -> None:
    if survey.effort_minutes <= 0:
        raise ValueError("effort_must_be_positive")
    if survey.detection_status == "not_detected" and survey.ended_at is None:
        raise ValueError("negative_survey_requires_end_time")
    _append(conn, "survey_sessions", "survey_id", survey.survey_id, asdict(survey), now)


def append_observation(conn: sqlite3.Connection, observation: LifecycleObservation, now: str) -> None:
    if observation.count is not None and observation.count < 0:
        raise ValueError("count_must_be_nonnegative")
    if observation.occupied_area_m2 is not None and observation.occupied_area_m2 < 0:
        raise ValueError("area_must_be_nonnegative")
    payload = asdict(observation)
    payload["media_ids"] = sorted(set(observation.media_ids))
    _append(conn, "lifecycle_observations", "observation_id", observation.observation_id, payload, now)


def append_media(conn: sqlite3.Connection, media: MediaEvidence, now: str) -> None:
    if len(media.sha256) != 64:
        raise ValueError("invalid_media_sha256")
    _append(conn, "media_evidence", "media_id", media.media_id, asdict(media), now)


def append_snapshot(conn: sqlite3.Connection, snapshot: EnvironmentalSnapshot, now: str) -> None:
    for value in (snapshot.relative_humidity_pct, snapshot.soil_moisture_pct, snapshot.canopy_pct):
        if value is not None and not 0 <= value <= 100:
            raise ValueError("percentage_out_of_range")
    _append(conn, "environmental_snapshots", "snapshot_id", snapshot.snapshot_id, asdict(snapshot), now)


def append_transition(conn: sqlite3.Connection, transition: StateTransition, now: str) -> None:
    if transition.to_state not in ALLOWED_TRANSITIONS[transition.from_state]:
        raise ValueError("invalid_lifecycle_transition")
    _append(conn, "lifecycle_transitions", "transition_id", transition.transition_id, asdict(transition), now)


def safe_site_view(site: MushroomSite, authorized_sensitive: bool = False) -> dict[str, Any]:
    payload = site.payload()
    if site.sensitive and not authorized_sensitive:
        payload["latitude"] = None
        payload["longitude"] = None
        payload["coordinate_confidence"] = "withheld"
    return payload
