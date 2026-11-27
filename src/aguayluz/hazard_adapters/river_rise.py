"""USGS river rate-of-rise adapter: sudden-rise detection on Puerto Rico stream gauges.

Input is the USGS Water Data OGC API ``continuous`` collection — instantaneous gage
height (``00065``, ft) and discharge (``00060``, ft³/s) for the PR bounding box over the
last few hours. The ingest (``scripts/ingest_usgs_river_rise.py``) freezes each response
before calling :func:`collect`; everything here is pure.

What the detector measures, per stream site:

* the stage rise over the last 15 minutes, 1 hour and 3 hours, looked up **by time**
  (PR gauges report every 5, 10 or 15 minutes, and arrive in hourly GOES bursts);
* the least-squares rate over the last hour;
* the discharge ratio against the 6-hour minimum, used only above a base-flow floor —
  discharge is rated from the same stage sensor, so it is never independent evidence;
* minutes until NWPS action/minor stage at the current rate, only where the NWPS gauge
  thresholds are in the same datum as the USGS reading (checked at a common timestamp).

A rise is graded ``NONE`` → ``ELEVATED_RISE`` → ``RAPID_RISE`` → ``FLASH_RISE`` against
``config/river_rise_thresholds.v1.json``. A RAPID or FLASH rise opens an *episode* (one
canonical event per site and onset); a revision is written only when the class, the peak
class or the "minor stage within 60 minutes" flag changes; the episode closes after a
quiet period, or after 24 hours with no fresh data.

This is detection of an **observed** rise, roughly an hour behind real time (satellite
relay), not a forecast and not an NWS warning.

Stdlib + :mod:`aguayluz.hazard_plane` only: the backend and the gui-parity CI import it.
"""
from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from aguayluz import CONFIG_DIR
from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus

SOURCE_AUTHORITY = "U.S. Geological Survey, Water Data for the Nation"
CANONICAL_PREFIX = "USGS_RISE:"
HAZARD_TYPE = "RIVER_STAGE_RATE_OF_RISE"
THRESHOLDS_FILE = CONFIG_DIR / "river_rise_thresholds.v1.json"
THRESHOLDS_SCHEMA = "aguayluz.river-rise-thresholds/v1"

STAGE = "00065"
DISCHARGE = "00060"
PARAMETER_CODES: tuple[str, ...] = (STAGE, DISCHARGE)
#: USGS statistic code for an instantaneous value.
INSTANTANEOUS = "00011"

#: Rise classes in rising order.
RISE_CLASSES: tuple[str, ...] = ("NONE", "ELEVATED_RISE", "RAPID_RISE", "FLASH_RISE")

#: Data states. Only OK and PENDING_CONFIRMATION may open an episode.
OK = "OK"
PENDING = "PENDING_CONFIRMATION"
STALE = "STALE"
INSUFFICIENT = "INSUFFICIENT"
NO_STAGE = "NO_STAGE"
SUPPRESSED = "SUPPRESSED"
USABLE_STATES = frozenset({OK, PENDING})

#: Built-in defaults; the config file overrides any of them.
DEFAULTS: dict[str, Any] = {
    "window_hours": 6,
    "grid_minutes": 15,
    "grid_slots": 25,
    "lookup_tolerance_minutes": 10,
    "min_points_1h": 3,
    "stale_after_minutes": 150,
    "spike_ft": 1.0,
    "confirm_prior_rise_ft": 0.25,
    "rising_since_tolerance_ft": 0.1,
    "excluded_qualifiers": ["Eqp", "Mnt", "Bkw", "Ice", "Dis", "Ssn", "***"],
    "classes": {
        "ELEVATED_RISE": {"rise_1h_ft": 1.0, "rise_3h_ft": 2.0, "q_ratio": 3.0},
        "RAPID_RISE": {"rise_15m_ft": 0.75, "rise_1h_ft": 2.0, "rise_3h_ft": 4.0},
        "FLASH_RISE": {"rise_15m_ft": 1.5, "rise_1h_ft": 4.0, "q_ratio": 5.0},
    },
    "headroom_fraction_per_h": {"ELEVATED_RISE": 0.15, "RAPID_RISE": 0.3, "FLASH_RISE": 0.6},
    "headroom_scale_max": 3.0,
    "q_ratio_min_base_cfs": 5.0,
    "q_ratio_min_delta_cfs": 100.0,
    "projection": {"horizon_minutes": 180, "escalate_within_minutes": 60,
                   "datum_tolerance_ft": 0.1, "datum_match_minutes": 5},
    "closure": {"quiet_minutes": 90, "quiet_max_rise_1h_ft": 0.1, "stale_close_hours": 24},
    "retention_days": 35,
}


# ------------------------------------------------------------------------ config


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_thresholds(path: Path | None = None) -> dict[str, Any]:
    """The thresholds config, with :data:`DEFAULTS` filled in under ``defaults``."""
    target = Path(path or THRESHOLDS_FILE)
    payload = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
    if payload and payload.get("schema_version") != THRESHOLDS_SCHEMA:
        raise ValueError(f"{target}: schema_version must be {THRESHOLDS_SCHEMA}")
    payload = dict(payload)
    payload["defaults"] = _deep_merge(DEFAULTS, payload.get("defaults") or {})
    payload.setdefault("sites", {})
    payload.setdefault("promotion", {"enabled": False, "classes": ["RAPID_RISE", "FLASH_RISE"]})
    payload.setdefault("calibration", {"status": "UNCALIBRATED_DEFAULTS"})
    return payload


def site_settings(config: dict[str, Any], site: str) -> dict[str, Any]:
    """Defaults merged with one site's overrides (``scale``, ``suppress``, ``note``, …)."""
    override = (config.get("sites") or {}).get(str(site)) or {}
    settings = _deep_merge(config.get("defaults") or DEFAULTS, {
        k: v for k, v in override.items() if k not in {"scale", "suppress", "note"}
    })
    settings["scale"] = float(override.get("scale", 1.0))
    settings["suppress"] = bool(override.get("suppress", False))
    settings["note"] = override.get("note")
    return settings


def promotion_classes(config: dict[str, Any]) -> tuple[str, ...]:
    classes = (config.get("promotion") or {}).get("classes") or ["RAPID_RISE", "FLASH_RISE"]
    return tuple(c for c in RISE_CLASSES if c in set(classes))


def class_rank(name: Any) -> int:
    return RISE_CLASSES.index(name) if name in RISE_CLASSES else 0


# ------------------------------------------------------------------- parsing


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def bare_site(value: Any) -> str:
    text = str(value or "").strip()
    return text.split("-", 1)[1] if text.upper().startswith("USGS-") else text


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _qualifiers(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(q.strip() for q in value.replace(";", ",").split(",") if q.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(q).strip() for q in value if str(q).strip())
    return (str(value),)


def approval_status(props: dict[str, Any]) -> str:
    """``approval_status`` (live API) with a fallback to the older ``approvals_status``."""
    value = props.get("approval_status")
    if value is None:
        value = props.get("approvals_status")
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return str(value or "Provisional")


@dataclass(frozen=True)
class Observation:
    time: datetime
    value: float
    qualifiers: tuple[str, ...] = ()
    approval: str = "Provisional"


@dataclass
class Collected:
    """Features sorted into per-site series, with arithmetic over every feature."""

    stage: dict[str, list[Observation]] = field(default_factory=dict)
    discharge: dict[str, list[Observation]] = field(default_factory=dict)
    time_series_ids: dict[str, dict[str, str]] = field(default_factory=dict)
    outcomes: dict[str, int] = field(default_factory=dict)
    source: int = 0
    retained: int = 0
    excluded: int = 0
    unresolved: int = 0

    def count(self, outcome: str, n: int = 1) -> None:
        self.outcomes[outcome] = self.outcomes.get(outcome, 0) + n
        if outcome == "retained":
            self.retained += n
        elif outcome.startswith("excluded"):
            self.excluded += n
        else:
            self.unresolved += n

    def move(self, outcome: str, n: int = 1) -> None:
        """Reclassify ``n`` already-retained features (spike removal)."""
        self.outcomes["retained"] = self.outcomes.get("retained", 0) - n
        self.retained -= n
        self.count(outcome, n)


def features_of(documents: Iterable[Any]) -> list[Any]:
    """Every feature in a list of GeoJSON FeatureCollection pages."""
    out: list[Any] = []
    for doc in documents:
        features = doc.get("features") if isinstance(doc, dict) else None
        if not isinstance(features, list):
            raise ValueError("response has no 'features' list")
        out.extend(features)
    return out


def collect(
    features: Iterable[Any],
    stream_sites: set[str] | None,
    excluded_qualifiers: Iterable[str] = DEFAULTS["excluded_qualifiers"],
    spike_ft: float = DEFAULTS["spike_ft"],
) -> Collected:
    """Sort features into per-site stage/discharge series; close the arithmetic.

    ``stream_sites`` is the set of bare USGS site numbers whose ``utility_assets`` row is
    a ``stream_gage``; ``None`` accepts every site (calibration over a known site list).
    Every feature lands in exactly one outcome, so ``retained + excluded + unresolved``
    always equals the number of features.
    """
    out = Collected()
    skip = {q.casefold() for q in excluded_qualifiers}
    staged: dict[tuple[str, str, str], dict[datetime, Observation]] = {}
    for feature in features:
        out.source += 1
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict):
            out.count("unresolved:not_a_feature")
            continue
        site = bare_site(props.get("monitoring_location_id"))
        when = parse_time(props.get("time"))
        pcode = str(props.get("parameter_code") or "").strip()
        if not site:
            out.count("unresolved:missing_site")
            continue
        if when is None:
            out.count("unresolved:missing_time")
            continue
        if pcode not in PARAMETER_CODES:
            out.count(f"excluded:parameter_{pcode or 'blank'}")
            continue
        statistic = str(props.get("statistic_id") or INSTANTANEOUS)
        if statistic != INSTANTANEOUS:
            out.count(f"excluded:statistic_{statistic}")
            continue
        if stream_sites is not None and site not in stream_sites:
            out.count("excluded:not_a_stream_site")
            continue
        qualifiers = _qualifiers(props.get("qualifier"))
        raw_value = props.get("value")
        value = _number(raw_value)
        if value is None:
            if raw_value is None and qualifiers:
                # USGS withholds the value and says why (e.g. RATINGDEV on discharge).
                out.count("excluded:value_withheld")
            elif raw_value is None:
                out.count("unresolved:missing_value")
            else:
                out.count("unresolved:unparseable_value")
            continue
        if any(q.casefold() in skip for q in qualifiers):
            out.count("excluded:qualifier")
            continue
        series_id = str(props.get("time_series_id") or f"{site}:{pcode}")
        bucket = staged.setdefault((site, pcode, series_id), {})
        if when in bucket:
            out.count("excluded:duplicate_time")
            continue
        bucket[when] = Observation(when, value, qualifiers, approval_status(props))
        out.count("retained")

    # One time series per site and parameter: the one with the most points (ties by id).
    chosen: dict[tuple[str, str], tuple[str, dict[datetime, Observation]]] = {}
    for (site, pcode, series_id), points in sorted(staged.items()):
        best = chosen.get((site, pcode))
        if best is None or len(points) > len(best[1]):
            if best is not None:
                out.move("excluded:secondary_time_series", len(best[1]))
            chosen[(site, pcode)] = (series_id, points)
        else:
            out.move("excluded:secondary_time_series", len(points))

    for (site, pcode), (series_id, points) in sorted(chosen.items()):
        series = [points[t] for t in sorted(points)]
        if pcode == STAGE:
            series, spikes = remove_spikes(series, spike_ft)
            if spikes:
                out.move("excluded:spike", spikes)
            out.stage[site] = series
        else:
            out.discharge[site] = series
        out.time_series_ids.setdefault(site, {})[pcode] = series_id
    return out


def remove_spikes(series: list[Observation], spike_ft: float) -> tuple[list[Observation], int]:
    """Drop interior points that stand out from two neighbours that agree with each other."""
    if len(series) < 3:
        return series, 0
    keep = [series[0]]
    removed = 0
    for i in range(1, len(series) - 1):
        prev, cur, nxt = keep[-1].value, series[i].value, series[i + 1].value
        up, down = cur - prev, cur - nxt
        neighbours_agree = abs(nxt - prev) <= spike_ft / 2
        if neighbours_agree and abs(up) > spike_ft and abs(down) > spike_ft and (up > 0) == (down > 0):
            removed += 1
            continue
        keep.append(series[i])
    keep.append(series[-1])
    return keep, removed


# ------------------------------------------------------------------- metrics


def value_at(series: list[Observation], when: datetime, tolerance: timedelta) -> float | None:
    """The last observation in ``(when - tolerance, when]``; None if there is none."""
    best: Observation | None = None
    for obs in series:
        if obs.time > when:
            break
        if obs.time > when - tolerance:
            best = obs
    return best.value if best else None


def slope_per_hour(points: list[Observation]) -> float | None:
    if len(points) < 2:
        return None
    t0 = points[0].time
    xs = [(p.time - t0).total_seconds() / 3600.0 for p in points]
    ys = [p.value for p in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _sig(value: float | None, figures: int = 3) -> float | None:
    if value is None or value == 0:
        return value
    return round(value, figures - 1 - int(math.floor(math.log10(abs(value)))))


def grid(series: list[Observation], end: datetime, *, step_minutes: int, slots: int,
         tolerance: timedelta, digits: int | None = 2) -> list[float | None]:
    """Values on a fixed grid ending at ``end`` (oldest first)."""
    out: list[float | None] = []
    for k in range(slots - 1, -1, -1):
        value = value_at(series, end - timedelta(minutes=step_minutes * k), tolerance)
        out.append(_round(value, digits) if digits is not None else _sig(value))
    return out


def rising_since(series: list[Observation], tolerance_ft: float) -> datetime | None:
    """Start of the current rise: the last base-level reading before the stage climbed.

    Walks back from the latest reading while no earlier reading exceeds the running
    minimum by more than ``tolerance_ft`` (that bounds the current rise), then returns the
    latest reading in that stretch still within ``tolerance_ft`` of its minimum — so a flat
    or gently noisy baseline does not drag the onset hours back.
    """
    if not series:
        return None
    low = series[-1].value
    start = len(series) - 1
    for i in range(len(series) - 2, -1, -1):
        if series[i].value > low + tolerance_ft:
            break
        low = min(low, series[i].value)
        start = i
    for obs in reversed(series[start:]):
        if obs.value <= low + tolerance_ft:
            return obs.time
    return series[start].time


def datum_check(stage: list[Observation], nwps: dict[str, Any] | None,
                tolerance_ft: float, match_minutes: float) -> str:
    """PASS when the NWPS stage equals the USGS reading at a common timestamp."""
    if not nwps:
        return "NO_NWPS"
    observed = nwps.get("observed") or {}
    nwps_stage = _number(observed.get("stage"))
    when = parse_time(observed.get("valid_time"))
    if nwps_stage is None or when is None:
        return "NO_COMMON_TIME"
    near = [o for o in stage if abs((o.time - when).total_seconds()) <= match_minutes * 60]
    if not near:
        return "NO_COMMON_TIME"
    closest = min(near, key=lambda o: abs((o.time - when).total_seconds()))
    return "PASS" if abs(closest.value - nwps_stage) <= tolerance_ft else "FAIL"


def _threshold_stage(nwps: dict[str, Any] | None, category: str) -> float | None:
    if not nwps:
        return None
    return _number(((nwps.get("thresholds") or {}).get(category) or {}).get("stage"))


def applied_thresholds(settings: dict[str, Any], headroom_ft: float | None) -> dict[str, dict[str, float]]:
    """Per-class thresholds for one site, scaled by headroom to action stage when known.

    A big river whose action stage sits 15 ft above base flow rises 2 ft in an hour
    without flooding; a small one cannot. The headroom scale is clamped to
    ``[1, headroom_scale_max]`` so a site sitting just below action stage never gets a
    hair-trigger threshold — the time-to-threshold projection covers that case instead.
    """
    out: dict[str, dict[str, float]] = {}
    cap = float(settings.get("headroom_scale_max", 3.0))
    for name, limits in (settings.get("classes") or {}).items():
        scale = float(settings.get("scale", 1.0))
        frac = (settings.get("headroom_fraction_per_h") or {}).get(name)
        base_1h = limits.get("rise_1h_ft")
        if headroom_ft is not None and headroom_ft > 0 and frac and base_1h:
            scale *= min(max(frac * headroom_ft / base_1h, 1.0), cap)
        out[name] = {
            key: round(value * scale, 3) if key.endswith("_ft") else float(value)
            for key, value in limits.items()
        }
    return out


def classify_rise(metrics: dict[str, Any], thresholds: dict[str, dict[str, float]],
                  *, pending: bool) -> tuple[str, list[str]]:
    """Highest class whose any criterion is met; a pending last point caps at ELEVATED."""
    def met(name: str) -> list[str]:
        limits = thresholds.get(name) or {}
        reasons: list[str] = []
        for key, metric in (("rise_15m_ft", "rise_15m_ft"), ("rise_1h_ft", "rise_1h_ft"),
                            ("rise_3h_ft", "rise_3h_ft")):
            limit, value = limits.get(key), metrics.get(metric)
            if limit is None or value is None:
                continue
            if key == "rise_15m_ft" and pending:
                continue
            if value >= limit:
                reasons.append(f"{metric} {value:g} ≥ {limit:g}")
        q_limit, q_ratio = limits.get("q_ratio"), metrics.get("q_ratio")
        if q_limit is not None and q_ratio is not None and q_ratio >= q_limit:
            if name != "FLASH_RISE":
                reasons.append(f"q_ratio {q_ratio:g} ≥ {q_limit:g}")
            else:
                # Discharge is rated from stage: at FLASH it needs a real stage rise too.
                elevated = (thresholds.get("ELEVATED_RISE") or {}).get("rise_1h_ft")
                rise = metrics.get("rise_1h_ft")
                if elevated is not None and rise is not None and rise >= elevated:
                    reasons.append(f"q_ratio {q_ratio:g} ≥ {q_limit:g} with rise_1h_ft {rise:g}")
        return reasons

    for name in ("FLASH_RISE", "RAPID_RISE", "ELEVATED_RISE"):
        reasons = met(name)
        if reasons:
            if pending and class_rank(name) > class_rank("ELEVATED_RISE"):
                return "ELEVATED_RISE", [*reasons, "capped: newest reading awaits confirmation"]
            return name, reasons
    return "NONE", []


@dataclass(frozen=True)
class SiteContext:
    """What the detector knows about a site besides its readings."""

    site: str
    asset_id: str | None = None
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    nwps: dict[str, Any] | None = None


def analyse_site(
    context: SiteContext,
    stage: list[Observation],
    discharge: list[Observation],
    now: datetime,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Metrics, projection, class and compact series for one site (pure)."""
    tol = timedelta(minutes=float(settings["lookup_tolerance_minutes"]))
    window_start = now - timedelta(hours=float(settings["window_hours"]))
    stage = [o for o in stage if window_start <= o.time <= now]
    discharge = [o for o in discharge if window_start <= o.time <= now]
    result: dict[str, Any] = {
        "site_no": context.site,
        "data_state": NO_STAGE,
        "metrics": {},
        "projection": {"to_action_minutes": None, "to_minor_minutes": None, "basis": None},
        "rise_class": "NONE",
        "class_reasons": [],
        "thresholds_applied": {},
        "rising_since": None,
        "latest": None,
        "latency_minutes": None,
        "series": None,
    }
    if not stage:
        return result
    latest = stage[-1]
    s_now = latest.value
    q_latest = discharge[-1] if discharge else None
    latency = (now - latest.time).total_seconds() / 60.0
    result["latest"] = {
        "time": iso(latest.time),
        "stage_ft": _round(s_now),
        "discharge_cfs": _sig(q_latest.value) if q_latest else None,
        "approval_status": latest.approval,
        "qualifiers": list(latest.qualifiers),
    }
    result["latency_minutes"] = round(latency, 1)

    def rise(minutes: int) -> float | None:
        before = value_at(stage, latest.time - timedelta(minutes=minutes), tol)
        return _round(s_now - before) if before is not None else None

    last_hour = [o for o in stage if o.time > latest.time - timedelta(minutes=60)]
    rate = slope_per_hour(last_hour) if len(last_hour) >= int(settings["min_points_1h"]) else None
    gaps = [(b.time - a.time).total_seconds() / 60 for a, b in zip(stage, stage[1:], strict=False)]
    q_now = q_latest.value if q_latest else None
    q_min = min(o.value for o in discharge) if discharge else None
    q_ratio = None
    if (q_now is not None and q_min is not None
            and q_min >= float(settings["q_ratio_min_base_cfs"])
            and q_now - q_min >= float(settings["q_ratio_min_delta_cfs"])):
        q_ratio = round(q_now / q_min, 2)
    metrics = {
        "rise_15m_ft": rise(15),
        "rise_1h_ft": rise(60),
        "rise_3h_ft": rise(180),
        "rate_ft_per_h": _round(rate),
        "min_stage_6h_ft": _round(min(o.value for o in stage)),
        "max_stage_6h_ft": _round(max(o.value for o in stage)),
        "q_now_cfs": _sig(q_now),
        "q_min_6h_cfs": _sig(q_min),
        "q_ratio": q_ratio,
        "points_6h": len(stage),
        "points_1h": len(last_hour),
        "max_gap_minutes": round(max(gaps), 1) if gaps else None,
    }
    result["metrics"] = metrics

    # A jump in the newest reading with no rise in the half hour before it waits one run
    # for confirmation (a sensor step looks exactly like this; a real flood rarely does).
    pending = False
    if len(stage) >= 2:
        jump = stage[-1].value - stage[-2].value
        before = value_at(stage, stage[-2].time - timedelta(minutes=30), tol)
        prior = stage[-2].value - before if before is not None else 0.0
        pending = jump > float(settings["spike_ft"]) and prior < float(settings["confirm_prior_rise_ft"])

    proj = settings["projection"]
    datum = datum_check(stage, context.nwps, float(proj["datum_tolerance_ft"]),
                        float(proj["datum_match_minutes"]))
    action = _threshold_stage(context.nwps, "action")
    minor = _threshold_stage(context.nwps, "minor")
    headroom = (action - metrics["min_stage_6h_ft"]) if datum == "PASS" and action is not None else None
    thresholds = applied_thresholds(settings, headroom)
    result["thresholds_applied"] = thresholds
    result["datum_check"] = datum

    def minutes_to(threshold: float | None) -> float | None:
        if datum != "PASS" or threshold is None:
            return None
        if s_now >= threshold:
            return 0.0
        if rate is None or rate <= 0:
            return None
        minutes = (threshold - s_now) / rate * 60.0
        return round(minutes, 0) if minutes <= float(proj["horizon_minutes"]) else None

    result["projection"] = {
        "to_action_minutes": minutes_to(action),
        "to_minor_minutes": minutes_to(minor),
        "action_stage_ft": action if datum == "PASS" else None,
        "minor_stage_ft": minor if datum == "PASS" else None,
        "basis": "nwps_thresholds_same_datum" if datum == "PASS" and (action or minor) else None,
    }

    if settings.get("suppress"):
        state = SUPPRESSED
    elif latency > float(settings["stale_after_minutes"]):
        state = STALE
    elif metrics["rise_1h_ft"] is None or len(last_hour) < int(settings["min_points_1h"]):
        state = INSUFFICIENT
    else:
        state = PENDING if pending else OK
    result["data_state"] = state
    if state in USABLE_STATES or state == STALE:
        cls, reasons = classify_rise(metrics, thresholds, pending=pending)
        result["rise_class"], result["class_reasons"] = cls, reasons
    result["rising_since"] = iso(rising_since(stage, float(settings["rising_since_tolerance_ft"])))

    step, slots = int(settings["grid_minutes"]), int(settings["grid_slots"])
    result["series"] = {
        "end": iso(latest.time),
        "step_minutes": step,
        "stage_ft": grid(stage, latest.time, step_minutes=step, slots=slots, tolerance=tol),
        "discharge_cfs": grid(discharge, latest.time, step_minutes=step, slots=slots,
                              tolerance=tol, digits=None) if discharge else None,
    }
    return result


# ------------------------------------------------------------------- episodes


def canonical_event_id(site: str, onset: datetime) -> str:
    return f"{CANONICAL_PREFIX}{site}:{onset.astimezone(timezone.utc):%Y%m%dT%H%MZ}"


def minor_within(row: dict[str, Any], settings: dict[str, Any]) -> bool:
    minutes = (row.get("projection") or {}).get("to_minor_minutes")
    limit = float(settings["projection"]["escalate_within_minutes"])
    return (
        isinstance(minutes, (int, float)) and minutes <= limit
        and row.get("datum_check") == "PASS"
        and class_rank(row.get("rise_class")) >= class_rank("RAPID_RISE")
    )


def material_state(site: str, onset: str, peak_class: str, minor_le_60: bool,
                   closed: bool) -> dict[str, Any]:
    """What makes a new revision: the peak class, the (sticky) minor-stage flag, closure.

    The current class moves every run (RAPID ↔ FLASH during a storm) and lives in the
    state file; only an escalation, the first projected minor-stage crossing or the
    closure is history worth a revision.
    """
    return {"site": site, "onset": onset, "peak_class": peak_class,
            "minor_within_60m": bool(minor_le_60), "closed": bool(closed)}


def material_digest(material: dict[str, Any]) -> str:
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def stable_record_id(event_id: str, material: dict[str, Any], supersedes: str | None) -> str:
    chained = sha256(f"{material_digest(material)}|{supersedes or 'HEAD'}".encode()).hexdigest()
    return f"{event_id}:REV:{chained[:20]}"


def episode_record(
    event_id: str,
    material: dict[str, Any],
    row: dict[str, Any],
    context: SiteContext,
    manifestation_id: str,
    *,
    supersedes: str | None,
    observed_to: datetime,
    effective_to: datetime | None = None,
    municipality_id: str | None = None,
    binding_evidence: str | None = None,
    closed_reason: str | None = None,
    include_series: bool = False,
) -> HazardRecord:
    onset = parse_time(material["onset"])
    if onset is None:
        raise ValueError(f"{event_id}: episode without an onset")
    observed_to = max(observed_to, onset)
    if effective_to is not None:
        effective_to = max(effective_to, onset)
    name = context.name or f"USGS {context.site}"
    peak = material["peak_class"].replace("_", " ").lower()
    values: dict[str, Any] = {
        **material,
        "material_digest": material_digest(material),
        "metrics": row.get("metrics") or {},
        "projection": row.get("projection") or {},
        "thresholds_applied": row.get("thresholds_applied") or {},
        "datum_check": row.get("datum_check"),
        "data_state": row.get("data_state"),
        "rise_class_at_revision": row.get("rise_class"),
        "latest": row.get("latest"),
        "nwps_lid": (context.nwps or {}).get("lid"),
        "class_reasons": row.get("class_reasons") or [],
    }
    if closed_reason:
        values["closed_reason"] = closed_reason
    if include_series:
        values["series"] = row.get("series")
    return HazardRecord(
        record_id=stable_record_id(event_id, material, supersedes),
        canonical_event_id=event_id,
        record_kind=RecordKind.EVENT,
        family=HazardFamily.HYDROMETEOROLOGY,
        hazard_type=HAZARD_TYPE,
        source_authority=SOURCE_AUTHORITY,
        source_record_id=context.site,
        manifestation_id=manifestation_id,
        title_raw=name,
        normalized_label=f"{name} — {peak}",
        status=RecordStatus.TERMINATED if material["closed"] else RecordStatus.ACTIVE,
        observed_from=onset,
        observed_to=observed_to,
        effective_from=onset,
        effective_to=effective_to,
        municipality_id=municipality_id,
        facility_id=context.asset_id,
        geography_basis=f"USGS_SITE_POINT:{binding_evidence or 'UNRESOLVED'}",
        geometry_precision="OBSERVED_POINT",
        provisional=True,
        supersedes_record_id=supersedes,
        raw_attributes={"site_no": context.site, "latitude": context.latitude,
                        "longitude": context.longitude},
        normalized_values=values,
    )


@dataclass(frozen=True)
class EpisodeStep:
    """What :func:`advance_episode` decided for one site this run."""

    action: str  # none | open | revise | close | hold
    material: dict[str, Any] | None = None
    event_id: str | None = None
    quiet_since: str | None = None
    closed_reason: str | None = None
    end: datetime | None = None


def advance_episode(
    head: HazardRecord | None,
    row: dict[str, Any] | None,
    now: datetime,
    settings: dict[str, Any],
    classes: tuple[str, ...],
    *,
    previous_quiet_since: str | None = None,
    not_before: datetime | None = None,
) -> EpisodeStep:
    """The episode state machine for one site (pure).

    ``head`` is the site's current *open* episode revision, if any; ``row`` is this run's
    :func:`analyse_site` result (``None`` when the site sent nothing). A quiet period is
    measured in observation time, so an hourly burst of four quiet readings counts the
    hour it covers, not the minute it arrived. ``not_before`` is just after the end of the
    site's last closed episode: a new rise from a plateau must not reuse that onset.
    """
    closure = settings["closure"]
    usable = row is not None and row.get("data_state") in USABLE_STATES
    cls = (row or {}).get("rise_class") or "NONE"
    latest_time = parse_time(((row or {}).get("latest") or {}).get("time"))

    if head is None:
        if not usable or cls not in classes or latest_time is None:
            return EpisodeStep("none")
        onset = parse_time(row.get("rising_since")) or latest_time
        if not_before is not None and onset < not_before:
            onset = min(not_before, latest_time)
        onset_text = iso(onset)
        material = material_state(row["site_no"], onset_text, cls,
                                  minor_within(row, settings), closed=False)
        return EpisodeStep("open", material, canonical_event_id(row["site_no"], onset))

    values = head.normalized_values
    site, onset_text = values["site"], values["onset"]
    minor_flag = bool(values.get("minor_within_60m", False))
    if not usable:
        last = parse_time(((row or {}).get("latest") or {}).get("time")) or head.observed_to \
            or head.observed_from
        if last is not None and now - last > timedelta(hours=float(closure["stale_close_hours"])):
            material = material_state(site, onset_text, values["peak_class"], minor_flag, closed=True)
            return EpisodeStep("close", material, head.canonical_event_id,
                               closed_reason="stale", end=last)
        return EpisodeStep("hold", event_id=head.canonical_event_id,
                           quiet_since=previous_quiet_since)

    if row is None or latest_time is None:  # usable rows always carry a latest reading
        return EpisodeStep("hold", event_id=head.canonical_event_id)
    rise_1h = (row.get("metrics") or {}).get("rise_1h_ft")
    quiet = cls == "NONE" and rise_1h is not None and rise_1h <= float(closure["quiet_max_rise_1h_ft"])
    quiet_since = (previous_quiet_since or iso(latest_time)) if quiet else None
    peak = max((values["peak_class"], cls), key=class_rank)
    minor_flag = minor_flag or minor_within(row, settings)
    if quiet and quiet_since is not None:
        since = parse_time(quiet_since)
        if since is not None and latest_time - since >= timedelta(minutes=float(closure["quiet_minutes"])):
            material = material_state(site, onset_text, peak, minor_flag, closed=True)
            return EpisodeStep("close", material, head.canonical_event_id,
                               closed_reason="receded", end=since)
    material = material_state(site, onset_text, peak, minor_flag, closed=False)
    if values.get("material_digest") != material_digest(material):
        return EpisodeStep("revise", material, head.canonical_event_id, quiet_since=quiet_since)
    return EpisodeStep("none", event_id=head.canonical_event_id, quiet_since=quiet_since)


__all__ = [
    "CANONICAL_PREFIX",
    "DEFAULTS",
    "DISCHARGE",
    "EpisodeStep",
    "HAZARD_TYPE",
    "INSTANTANEOUS",
    "Observation",
    "PARAMETER_CODES",
    "RISE_CLASSES",
    "SOURCE_AUTHORITY",
    "STAGE",
    "SUPPRESSED",
    "SiteContext",
    "THRESHOLDS_FILE",
    "USABLE_STATES",
    "advance_episode",
    "analyse_site",
    "applied_thresholds",
    "approval_status",
    "bare_site",
    "canonical_event_id",
    "class_rank",
    "classify_rise",
    "collect",
    "datum_check",
    "episode_record",
    "features_of",
    "grid",
    "load_thresholds",
    "material_digest",
    "material_state",
    "minor_within",
    "parse_time",
    "promotion_classes",
    "remove_spikes",
    "rising_since",
    "site_settings",
    "slope_per_hour",
    "stable_record_id",
    "value_at",
]
