"""Read-only v2 research consistency boundary. No ingestion or application surface.

PASS covers only checked constraints. External permissions, metadata, commitment
clocks, media, taxonomy and identity remain unverified. Every authority flag is
false. RAW bytes stay with the caller: nothing here persists, rewrites or exports
source records. No baseline v1 schema is modified or implicitly migrated.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import struct
import zoneinfo
from collections import deque
from datetime import datetime, timezone
from importlib import resources
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator, FormatChecker

IMPLEMENTATION_VERSION = "2.0.3"
SCHEMA_VERSION = "2.0.0"
SCHEMA_SHA256 = "bfe7e8628d93adb149c8b79672cbfb4c8025c56d1de3505cb07a9eec2f2a8aba"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas/mycelial-consistency/v2/contracts.schema.json"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_ROWS = 512
MAX_DEPTH = 48
MAX_NODES = 50000
# Operational key bounds, not an assertion that a matching key exists in IANA.
MAX_ZONE_KEY_LENGTH = 255
MAX_TZIF_BYTES = 1024 * 1024
MAX_TZIF_TRANSITIONS = 16384
MAX_TZIF_TYPES = 256
MAX_TZIF_DESIGNATIONS = 4096
MAX_TZIF_LEAPS = 1024
MAX_TZIF_FOOTER = 256
MAX_TZPATH_ROOTS = 32
ZONE_KEY = re.compile(r"[A-Za-z0-9_+-]{1,64}(?:/[A-Za-z0-9_+-]{1,64})*")
SERIALIZATION = "aguayluz.sorted-json-utf8/v1"
KINDS = {
    "mycelial_field_site": ("site", "site_id"),
    "mycelial_study_target": ("target", "target_id"),
    "mycelial_field_survey": ("survey", "survey_id"),
    "mycelial_fruiting_observation": ("observation", "observation_id"),
    "mycelial_source_acquisition_receipt": ("receipt", "receipt_id"),
    "mycelial_substrate_unit": ("substrate", "substrate_unit_id"),
    "mycelial_preschedule_commitment": ("preschedule", "commitment_id"),
}
# RFC 3339 offset components must be checked before fromisoformat can normalize
# them. Leap seconds remain unsupported, as in v2.0.0; no raw string is changed.
STAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt]"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?"
    r"(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)


class InputRejected(ValueError):
    """Only constant reason codes; never echo input or exception details."""


def _guard(value: Any) -> None:
    stack = [(value, 0)]
    nodes = 0
    while stack:
        obj, depth = stack.pop()
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise InputRejected("STRUCTURE_RESOURCE_LIMIT")
        if type(obj) is dict:
            if any(type(k) is not str for k in obj):
                raise InputRejected("NON_JSON_OBJECT_KEY")
            stack.extend((v, depth + 1) for v in obj.values())
            stack.extend((k, depth + 1) for k in obj)
        elif type(obj) is list:
            stack.extend((v, depth + 1) for v in obj)
        elif type(obj) is float:
            if not math.isfinite(obj):
                raise InputRejected("NONFINITE_VALUE")
        elif obj is not None and type(obj) not in (str, int, bool):
            raise InputRejected("NON_JSON_VALUE")
        if type(obj) is str:
            try:
                obj.encode("utf-8")
            except UnicodeEncodeError:
                raise InputRejected("INVALID_UNICODE") from None


def load_strict(data: bytes) -> Any:
    """Decode once without duplicate-key loss, string normalization or NaN."""
    if type(data) is not bytes:
        raise InputRejected("INPUT_MUST_BE_BYTES")
    if len(data) > MAX_INPUT_BYTES:
        raise InputRejected("INPUT_SIZE_LIMIT")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise InputRejected("DUPLICATE_JSON_KEY")
            out[key] = value
        return out

    def constant(_: str) -> None:
        raise InputRejected("NONFINITE_VALUE")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        _guard(value)
        return value
    except InputRejected:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise InputRejected("INVALID_JSON_OR_ENCODING") from None


def logical_sha256(value: Any) -> str:
    """Logical serialization hash; NEVER evidence of original transport bytes."""
    _guard(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError):
        raise InputRejected("LOGICAL_SERIALIZATION_FAILED") from None
    if len(raw) > MAX_INPUT_BYTES:
        raise InputRejected("INPUT_SIZE_LIMIT")
    return hashlib.sha256(raw).hexdigest()


def _time(value: str) -> datetime:
    if not STAMP.fullmatch(value):
        raise ValueError("INVALID_TIMESTAMP")
    stamp = datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("NAIVE_TIMESTAMP")
    # All later temporal comparisons require an instant representable in UTC.
    # Keep this as validation only: return the original parsed representation.
    try:
        stamp.astimezone(timezone.utc)
    except OverflowError:
        raise ValueError("TIMESTAMP_UTC_OUT_OF_RANGE") from None
    return stamp


def _read_regular_tzif(path: Path) -> bytes:
    """One bounded snapshot from a regular local file, not a later parser reopen.

    TZPATH and installed packages are trusted configuration. This does not promise
    a wall-clock deadline on a failing kernel or remote-mounted filesystem.
    """
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise InputRejected("TIMEZONE_RESOURCE_NOT_REGULAR")
        if before.st_size > MAX_TZIF_BYTES:
            raise InputRejected("TIMEZONE_RESOURCE_LIMIT")
        # The descriptor, not the path, is read. The immutable returned buffer is
        # both validated and decoded; filesystem mutations cannot replace it.
        chunks = []
        remaining = MAX_TZIF_BYTES + 1
        read_calls = 0
        while remaining:
            read_calls += 1
            if read_calls > 64:
                raise InputRejected("TIMEZONE_RESOURCE_LIMIT")
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
        def identity(v):
            return (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
        if identity(before) != identity(after) or len(data) != before.st_size:
            raise InputRejected("TIMEZONE_RESOURCE_CHANGED")
        if len(data) > MAX_TZIF_BYTES:
            raise InputRejected("TIMEZONE_RESOURCE_LIMIT")
        return data
    finally:
        os.close(fd)


def _read_zone_bytes(key: str) -> bytes:
    """Follow system-root priority; fall back only when a file is not found.

    The supported resource class is regular local files, including unpacked
    tzdata wheels. Zip/custom import-resource backends fail explicitly rather
    than entering an unbounded decompressor or user-defined stream.
    """
    roots = tuple(zoneinfo.TZPATH)
    if len(roots) > MAX_TZPATH_ROOTS:
        raise InputRejected("TIMEZONE_RESOURCE_LIMIT")
    for root in roots:
        try:
            return _read_regular_tzif(Path(root).joinpath(*key.split("/")))
        except FileNotFoundError:
            continue
    try:
        resource = resources.files("tzdata.zoneinfo").joinpath(*key.split("/"))
    except ModuleNotFoundError:
        raise ZoneInfoNotFoundError(key) from None
    try:
        path = Path(os.fspath(resource))
    except TypeError:
        raise InputRejected("TIMEZONE_RESOURCE_BACKEND_UNSUPPORTED") from None
    try:
        return _read_regular_tzif(path)
    except FileNotFoundError:
        raise ZoneInfoNotFoundError(key) from None


def _tzif_block(data: bytes, offset: int, time_size: int) -> tuple[bytes, int]:
    """Check counted arrays before allocating or handing them to the decoder."""
    if offset + 44 > len(data) or data[offset:offset + 4] != b"TZif":
        raise InputRejected("TIMEZONE_DATA_INVALID")
    version = data[offset + 4:offset + 5]
    if version not in (b"\x00", b"2", b"3", b"4"):
        raise InputRejected("TIMEZONE_TZIF_VERSION_UNSUPPORTED")
    utc_count, std_count, leap_count, time_count, type_count, char_count = (
        struct.unpack_from(">6I", data, offset + 20)
    )
    if type_count < 1 or char_count < 1:
        raise InputRejected("TIMEZONE_DATA_INVALID")
    if type_count > MAX_TZIF_TYPES or char_count > MAX_TZIF_DESIGNATIONS:
        raise InputRejected("TIMEZONE_RESOURCE_LIMIT")
    if time_count > MAX_TZIF_TRANSITIONS or leap_count > MAX_TZIF_LEAPS:
        raise InputRejected("TIMEZONE_RESOURCE_LIMIT")
    if utc_count not in (0, type_count) or std_count not in (0, type_count):
        raise InputRejected("TIMEZONE_DATA_INVALID")
    begin = offset + 44
    end = (begin + time_count * (time_size + 1) + type_count * 6 + char_count
           + leap_count * (time_size + 4) + std_count + utc_count)
    if end > len(data):
        raise InputRejected("TIMEZONE_DATA_INVALID")
    fmt = ">i" if time_size == 4 else ">q"
    times_end = begin + time_count * time_size
    previous = None
    for (transition,) in struct.iter_unpack(fmt, data[begin:times_end]):
        if previous is not None and transition <= previous:
            raise InputRejected("TIMEZONE_DATA_INVALID")
        previous = transition
    indices_end = times_end + time_count
    if any(index >= type_count for index in data[times_end:indices_end]):
        raise InputRejected("TIMEZONE_DATA_INVALID")
    types_end = indices_end + type_count * 6
    names_end = types_end + char_count
    names = data[types_end:names_end]
    # This conservative decoder-compatible subset uses printable ASCII names.
    # It is not a claim that RFC 9636 forbids other designation encodings.
    if names[-1] != 0:
        raise InputRejected("TIMEZONE_DATA_INVALID")
    if any(c != 0 and not 32 <= c <= 126 for c in names):
        raise InputRejected("TIMEZONE_DECODER_RANGE_UNSUPPORTED")
    for utc_offset, dst, index in struct.iter_unpack(">iBB", data[indices_end:types_end]):
        if dst not in (0, 1) or index >= char_count or names.find(b"\x00", index) == -1:
            raise InputRejected("TIMEZONE_DATA_INVALID")
        # Current Python readers use signed abbreviation indices internally, and
        # datetime offsets must be strictly between -24h and +24h.
        if index > 127 or not -86400 < utc_offset < 86400:
            raise InputRejected("TIMEZONE_DECODER_RANGE_UNSUPPORTED")
    leap_end = names_end + leap_count * (time_size + 4)
    last_time = last_correction = None
    leap_fmt = ">ii" if time_size == 4 else ">qi"
    for i, (instant, correction) in enumerate(struct.iter_unpack(leap_fmt, data[names_end:leap_end])):
        if instant < 0 or (last_time is not None and instant <= last_time):
            raise InputRejected("TIMEZONE_DATA_INVALID")
        if last_correction is None:
            if version != b"4" and correction not in (-1, 1):
                raise InputRejected("TIMEZONE_DATA_INVALID")
        elif abs(correction - last_correction) != 1:
            if not (version == b"4" and i == leap_count - 1 and correction == last_correction):
                raise InputRejected("TIMEZONE_DATA_INVALID")
        last_time, last_correction = instant, correction
    standards = data[leap_end:leap_end + std_count]
    universals = data[leap_end + std_count:end]
    if any(v not in (0, 1) for v in standards + universals):
        raise InputRejected("TIMEZONE_DATA_INVALID")
    if any(v and (not standards or not standards[i]) for i, v in enumerate(universals)):
        raise InputRejected("TIMEZONE_DATA_INVALID")
    return version, end


def _validate_tzif(data: bytes) -> None:
    """Bound a complete TZif 1/2/3/4 resource, including both counted blocks.

    This checks a documented structural/decoder-compatible subset, not all RFC
    semantics or the authority/correctness of a time zone's civil-time rules.
    """
    if type(data) is not bytes or not data:
        raise InputRejected("TIMEZONE_DATA_INVALID")
    if len(data) > MAX_TZIF_BYTES:
        raise InputRejected("TIMEZONE_RESOURCE_LIMIT")
    version, end = _tzif_block(data, 0, 4)
    if version == b"\x00":
        if end != len(data):
            raise InputRejected("TIMEZONE_DATA_INVALID")
        return
    second_version, end = _tzif_block(data, end, 8)
    if second_version != version:
        raise InputRejected("TIMEZONE_DATA_INVALID")
    footer = data[end:]
    if not 2 <= len(footer) <= MAX_TZIF_FOOTER:
        raise InputRejected("TIMEZONE_DATA_INVALID")
    if footer[:1] != b"\n" or footer[-1:] != b"\n":
        raise InputRejected("TIMEZONE_DATA_INVALID")
    if any(not 32 <= c <= 126 for c in footer[1:-1]):
        raise InputRejected("TIMEZONE_DATA_INVALID")


def _zone(key: str) -> ZoneInfo:
    """Decode only the same bounded immutable bytes that passed preflight."""
    if len(key) > MAX_ZONE_KEY_LENGTH or ZONE_KEY.fullmatch(key) is None:
        raise InputRejected("TIMEZONE_KEY_INVALID")
    try:
        data = _read_zone_bytes(key)
        _validate_tzif(data)
        with BytesIO(data) as snapshot:
            return ZoneInfo.from_file(snapshot, key=key)
    except InputRejected:
        raise
    except ZoneInfoNotFoundError:
        raise InputRejected("UNRECOGNIZED_TIMEZONE") from None
    except OSError:
        raise InputRejected("TIMEZONE_DATA_ACCESS_FAILURE") from None
    except (ValueError, EOFError, struct.error, AssertionError, IndexError, OverflowError):
        raise InputRejected("TIMEZONE_DATA_INVALID") from None


def _format_checker() -> FormatChecker:
    # Explicit standard-library checks avoid silently disabled optional formats.
    checker = FormatChecker(formats=[])

    @checker.checks("date-time", raises=(ValueError, OverflowError))
    def timestamp(value: Any) -> bool:
        return not isinstance(value, str) or bool(_time(value))

    @checker.checks("uri", raises=ValueError)
    def uri(value: Any) -> bool:
        if not isinstance(value, str):
            return True
        return bool(urlsplit(value).scheme) and not any(c.isspace() or ord(c) < 32 for c in value)

    return checker


def schema_for(record_type: str) -> dict[str, Any]:
    """New copy per call; mutation cannot poison another validation."""
    if record_type not in KINDS:
        raise InputRejected("UNKNOWN_RECORD_TYPE")
    try:
        raw = SCHEMA_PATH.read_bytes()
    except OSError:
        raise InputRejected("TRUSTED_SCHEMA_UNAVAILABLE") from None
    if hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256:
        raise InputRejected("TRUSTED_SCHEMA_HASH_MISMATCH")
    root = load_strict(raw)
    root["oneOf"] = [{"$ref": "#/$defs/" + KINDS[record_type][0]}]
    return root


def _result(errors: list[str], holds: list[str] | None = None) -> dict[str, Any]:
    return {
        "state": "FAIL" if errors else "PASS_CHECKED_CONSTRAINTS",
        "reason_codes": sorted(set(errors)),
        "review_hold_codes": sorted(set(holds or [])),
        "scope": "read_only_v2_structural_and_selected_semantic_consistency",
        "record_admitted": False,
        "field_authorized": False,
        "public_export_authorized": False,
        "model_eligible": False,
    }


def _kind(record: Any) -> str | None:
    if type(record) is dict and type(record.get("record_type")) is str and record["record_type"] in KINDS:
        return record["record_type"]
    return None


def check_record(record: Any) -> dict[str, Any]:
    """Checks a record; passing a reference string does not verify its evidence."""
    try:
        _guard(record)
        kind = _kind(record)
        if kind is None:
            return _result(["UNKNOWN_RECORD_TYPE"])
        validator = Draft202012Validator(schema_for(kind), format_checker=_format_checker())
        if not validator.is_valid(record):
            return _result(["SCHEMA_INVALID"])
    except InputRejected as exc:
        return _result([str(exc)])
    errors: list[str] = []
    holds = ["EXTERNAL_EVIDENCE_NOT_AUTHENTICATED", "PUBLIC_DISCLOSURE_NOT_REVIEWED"]
    if "review_state" in record and record["review_state"] != "protocol_eligible":
        holds.append("REVIEW_STATE_NOT_ELIGIBLE")
    family = KINDS[kind][0]
    if family == "site":
        holds.append("ACCESS_AUTHORITY_NOT_VERIFIED")
    elif family == "survey":
        observed_count = len(record["observer_pseudonyms"])
        count_matches = record["observer_count"] == observed_count
        if not count_matches:
            errors.append("OBSERVER_COUNT_MISMATCH")
        start, end = record["started_at"], record["ended_at"]
        if (start is None) != (end is None):
            errors.append("TIME_PAIR_INCOMPLETE")
        if start is not None and end is not None:
            seconds = (_time(end) - _time(start)).total_seconds()
            if seconds < 0:
                errors.append("REVERSED_SURVEY_TIME")
            if record["person_minutes"] > 0:
                if seconds <= 0:
                    errors.append("POSITIVE_EFFORT_WITHOUT_DURATION")
                # Never coerce an untrusted arbitrary-size count into a float.
                # The input structure bounds observed_count; mismatches already fail.
                elif count_matches and record["person_minutes"] > seconds / 60 * observed_count + 1e-9:
                    errors.append("EFFORT_EXCEEDS_PERSON_TIME_CAPACITY")
        elif record["person_minutes"] > 0:
            errors.append("POSITIVE_EFFORT_WITHOUT_TIME")
        if record["detection_status"] == "detected" and (start is None or end is None or record["observer_count"] < 1 or record["person_minutes"] <= 0):
            errors.append("DETECTION_WITHOUT_SEARCH_EVIDENCE")
        try:
            zone = _zone(record["timezone"])
            for timestamp in (start, end, record["scheduled_for"]):
                if timestamp is not None:
                    stamp = _time(timestamp)
                    if stamp.utcoffset() != stamp.astimezone(zone).utcoffset():
                        holds.append("TIMESTAMP_ZONE_REPRESENTATION_REVIEW")
        except InputRejected as exc:
            errors.append(str(exc))
        except OverflowError:
            errors.append("TIMESTAMP_ZONE_OUT_OF_RANGE")
        except (ZoneInfoNotFoundError, ValueError):
            errors.append("UNRECOGNIZED_TIMEZONE")
        if record["person_minutes"] == 0 and record["substrate_unit_ids"]:
            errors.append("EXAMINED_UNITS_WITHOUT_EFFORT")
        holds.append("PRESCHEDULE_AUTHORITY_NOT_VERIFIED")
    elif family == "target":
        holds.append("TARGET_DEFINITION_AND_SENSITIVITY_NOT_VERIFIED")
    elif family == "observation":
        count = record["count"]
        if count["method"] == "range" and count["upper_bound"] < count["lower_bound"]:
            errors.append("COUNT_RANGE_INVALID")
        mids = [m["measurement_id"] for m in record["measurements"]]
        if len(mids) != len(set(mids)):
            errors.append("DUPLICATE_MEASUREMENT_ID")
        holds.extend(["BIOLOGICAL_MEDIA_NOT_VERIFIED", "EPISODE_INDIVIDUAL_ADJUDICATION_NOT_VERIFIED"])
    elif family == "receipt":
        end = record["retrieval_completed_at"]
        if end is not None and _time(end) < _time(record["retrieval_started_at"]):
            errors.append("REVERSED_ACQUISITION_TIME")
        if record["status"] == "complete":
            transport = record["transport"]
            code = transport["status_code"]
            if code is None or not 200 <= code < 300 or code in (204, 206) or transport["final_url"] is None:
                errors.append("COMPLETE_SOURCE_HTTP_STATUS_MISMATCH")
        holds.extend(["ORIGINAL_BYTES_NOT_CHECKED", "RIGHTS_COORDINATE_POLICY_NOT_VERIFIED"])
    elif family == "substrate":
        if record["supersedes_substrate_unit_id"] == record["substrate_unit_id"]:
            errors.append("SELF_SUPERSESSION")
        holds.append("SUBSTRATE_IDENTITY_NOT_VERIFIED")
    elif family == "preschedule":
        plans = record["manifest"]["plans"]
        for field in ("plan_entry_id", "survey_id"):
            values = [p[field] for p in plans]
            if len(values) != len(set(values)):
                errors.append("DUPLICATE_PLAN_IDENTITY")
        if logical_sha256(record["manifest"]) != record["manifest_sha256"]:
            errors.append("PLAN_MANIFEST_HASH_MISMATCH")
        if any(_time(record["committed_at"]) >= _time(p["scheduled_for"]) for p in plans):
            errors.append("COMMITMENT_NOT_BEFORE_PLANNED_VISIT")
        for p in plans:
            if set(p["substrate_unit_ids"]) != set(p["substrate_definition_sha256"]):
                errors.append("PLAN_SUBSTRATE_HASH_SET_MISMATCH")
        if record["supersedes_commitment_id"] == record["commitment_id"]:
            errors.append("SELF_SUPERSESSION")
        holds.append("PRESCHEDULE_AUTHORITY_NOT_VERIFIED")
    return _result(errors, holds)


def check_bundle(records: list[Any]) -> dict[str, Any]:
    """Whole-row, namespace-specific binding. All tied candidates are preserved.

Even malformed duplicates block resolution. No caller receives an ingest token.
Preschedule hashes test declared logical identity, not independent clock evidence.
"""
    if type(records) is not list:
        raise InputRejected("BUNDLE_MUST_BE_LIST")
    if not records or len(records) > MAX_ROWS:
        raise InputRejected("BUNDLE_SIZE_LIMIT")
    _guard(records)
    checks = [check_record(row) for row in records]
    usable = [not row["reason_codes"] for row in checks]
    groups: dict[tuple[str, str], list[int]] = {}
    deps: list[set[int]] = [set() for _ in records]
    candidates: list[dict[str, Any]] = []
    for i, row in enumerate(records):
        kind = _kind(row)
        if kind is not None:
            value = row.get(KINDS[kind][1])
            if type(value) is str:
                groups.setdefault((kind, value), []).append(i)
    for indices in groups.values():
        if len(indices) > 1:
            for i in indices:
                checks[i]["reason_codes"].append("DUPLICATE_STABLE_ID_REVIEW")

    def fail(i: int, code: str) -> None:
        checks[i]["reason_codes"].append(code)

    def ref(
        family: str, value: str, i: int, field: str, *,
        edge_role: Literal["active_use", "historical_predecessor"] = "active_use",
    ) -> dict[str, Any] | None:
        kind = next(k for k, v in KINDS.items() if v[0] == family)
        indices = groups.get((kind, value), [])
        # Only an explicitly superseded requester supplies historical definitions.
        # A historical predecessor may be inspected but never promotes active use.
        role = (
            "historical_definition"
            if edge_role == "active_use" and records[i].get("review_state") == "superseded"
            else edge_role
        )
        candidates.append({
            "requester_row": i, "reference_field": field,
            "candidate_rows": list(indices), "edge_role": role,
        })
        deps[i].update(indices)
        if len(indices) != 1:
            fail(i, "MISSING_OR_AMBIGUOUS_REFERENCE")
            return None
        j = indices[0]
        if not usable[j]:
            fail(i, "DEPENDENCY_CONSISTENCY_FAILURE")
            return None
        state = records[j].get("review_state")
        if state == "superseded" and role in {"historical_predecessor", "historical_definition"}:
            # All structural/hash/time/dependency checks still execute on archives.
            hold = (
                "HISTORICAL_PREDECESSOR_NOT_ACTIVE"
                if role == "historical_predecessor" else "HISTORICAL_DEFINITION_NOT_ACTIVE"
            )
            checks[i]["review_hold_codes"].append(hold)
        elif state in {"rejected", "retired", "superseded"}:
            fail(i, "REFERENCE_REVIEW_STATE_NOT_USABLE")
        return records[j]

    for i, row in enumerate(records):
        if not usable[i]:
            continue
        family = KINDS[row["record_type"]][0]
        if family == "substrate":
            ref("site", row["site_id"], i, "site_id")
            if row["supersedes_substrate_unit_id"] is not None:
                old = ref("substrate", row["supersedes_substrate_unit_id"], i, "supersedes_substrate_unit_id", edge_role="historical_predecessor")
                if old and (old["site_id"] != row["site_id"] or _time(old["registered_at"]) >= _time(row["registered_at"])):
                    fail(i, "SUBSTRATE_SUPERSESSION_CONFLICT")
        elif family == "preschedule":
            for p in row["manifest"]["plans"]:
                site = ref("site", p["site_id"], i, "plan.site_id")
                target = ref("target", p["target_id"], i, "plan.target_id")
                for entity, key in ((site, "site_definition_sha256"), (target, "target_definition_sha256")):
                    if entity is not None and logical_sha256(entity) != p[key]:
                        fail(i, "PLAN_DEFINITION_HASH_MISMATCH")
                for unit_id in p["substrate_unit_ids"]:
                    sub = ref("substrate", unit_id, i, "plan.substrate_unit_ids")
                    if sub is not None:
                        if sub["site_id"] != p["site_id"]:
                            fail(i, "SUBSTRATE_SITE_MISMATCH")
                        if _time(sub["registered_at"]) > _time(row["committed_at"]):
                            fail(i, "SUBSTRATE_REGISTERED_AFTER_COMMITMENT")
                        if logical_sha256(sub) != p["substrate_definition_sha256"][unit_id]:
                            fail(i, "PLAN_DEFINITION_HASH_MISMATCH")
            if row["supersedes_commitment_id"] is not None:
                old = ref("preschedule", row["supersedes_commitment_id"], i, "supersedes_commitment_id", edge_role="historical_predecessor")
                if old and _time(old["committed_at"]) >= _time(row["committed_at"]):
                    fail(i, "COMMITMENT_SUPERSESSION_TIME_CONFLICT")
        elif family == "survey":
            ref("site", row["site_id"], i, "site_id")
            target = ref("target", row["target_scope"]["target_id"], i, "target_scope.target_id")
            if target is not None and target["kind"] != row["target_scope"]["kind"]:
                fail(i, "SURVEY_TARGET_KIND_MISMATCH")
            for unit_id in row["substrate_unit_ids"]:
                sub = ref("substrate", unit_id, i, "substrate_unit_ids")
                if sub is not None and sub["site_id"] != row["site_id"]:
                    fail(i, "SUBSTRATE_SITE_MISMATCH")
            commitment = ref("preschedule", row["preschedule_commitment_id"], i, "preschedule_commitment_id")
            if commitment is not None:
                matched = [p for p in commitment["manifest"]["plans"] if p["plan_entry_id"] == row["plan_entry_id"]]
                if len(matched) != 1:
                    fail(i, "MISSING_OR_AMBIGUOUS_PLAN_ENTRY")
                else:
                    p = matched[0]
                    fields = ("survey_id", "site_id", "protocol_id", "protocol_version")
                    if any(p[k] != row[k] for k in fields) or p["target_id"] != row["target_scope"]["target_id"] or _time(p["scheduled_for"]) != _time(row["scheduled_for"]):
                        fail(i, "SURVEY_PLAN_BINDING_CONFLICT")
                    actual, planned = set(row["substrate_unit_ids"]), set(p["substrate_unit_ids"])
                    if not actual <= planned:
                        fail(i, "UNPLANNED_SUBSTRATE_UNIT")
                    if row["visit_status"] == "completed" and actual != planned:
                        fail(i, "COMPLETED_SUBSTRATE_SCOPE_MISMATCH")
                    if row["person_minutes"] != p["intended_person_minutes"] or row["observer_count"] != p["intended_observer_count"]:
                        checks[i]["review_hold_codes"].append("PLANNED_ACTUAL_EFFORT_DEVIATION")
                if row["started_at"] is not None and _time(commitment["committed_at"]) >= _time(row["started_at"]):
                    fail(i, "COMMITMENT_NOT_BEFORE_ACTUAL_VISIT")
        elif family == "observation":
            survey = ref("survey", row["survey_id"], i, "survey_id")
            ref("site", row["site_id"], i, "site_id")
            ref("target", row["target_id"], i, "target_id")
            sub = ref("substrate", row["substrate_unit_id"], i, "substrate_unit_id")
            if sub is not None and sub["site_id"] != row["site_id"]:
                fail(i, "SUBSTRATE_SITE_MISMATCH")
            if survey is not None:
                if row["site_id"] != survey["site_id"] or row["target_id"] != survey["target_scope"]["target_id"]:
                    fail(i, "OBSERVATION_SURVEY_IDENTITY_CONFLICT")
                if survey["detection_status"] != "detected":
                    fail(i, "BODY_LINKED_TO_NONDETECTING_SURVEY")
                if row["substrate_unit_id"] not in survey["substrate_unit_ids"]:
                    fail(i, "BODY_OUTSIDE_EXAMINED_SUBSTRATE")
                start, end = survey["started_at"], survey["ended_at"]
                if start is None or end is None or not _time(start) <= _time(row["observed_at"]) <= _time(end):
                    fail(i, "OBSERVATION_OUTSIDE_SURVEY_INTERVAL")

    # Kahn's algorithm detects cycles and their downstream dependents without recursion.
    reverse: list[set[int]] = [set() for _ in records]
    remaining = [len(d) for d in deps]
    for i, required in enumerate(deps):
        for j in required:
            reverse[j].add(i)
    queue = deque(i for i, n in enumerate(remaining) if n == 0)
    while queue:
        i = queue.popleft()
        for j in reverse[i]:
            remaining[j] -= 1
            if remaining[j] == 0:
                queue.append(j)
    for i, n in enumerate(remaining):
        if n:
            fail(i, "CYCLIC_OR_CYCLE_DEPENDENT_REFERENCE")
    queue = deque(i for i, c in enumerate(checks) if c["reason_codes"])
    visited = set(queue)
    while queue:
        i = queue.popleft()
        for j in reverse[i]:
            fail(j, "DEPENDENCY_CONSISTENCY_FAILURE")
            if j not in visited:
                visited.add(j)
                queue.append(j)
    results = [_result(c["reason_codes"], c["review_hold_codes"]) for c in checks]
    passed = sum(r["state"] == "PASS_CHECKED_CONSTRAINTS" for r in results)
    return {
        "state": "PASS_CHECKED_CONSTRAINTS" if passed == len(records) else "FAIL",
        "input_rows": len(records), "passed_checked_constraints": passed,
        "failed_rows": len(records) - passed, "rows": results,
        "reference_candidates": candidates,
        "canonical_records_admitted": 0, "model_eligible": False,
        "record_admitted": False, "field_authorized": False, "public_export_authorized": False,
    }


def check_bytes(data: bytes) -> dict[str, Any]:
    """Sole intended untrusted-input entrypoint; does not persist rejected bytes."""
    try:
        value = load_strict(data)
        return check_bundle(value) if type(value) is list else check_record(value)
    except InputRejected as exc:
        return _result([str(exc)])
