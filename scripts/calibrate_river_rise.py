#!/usr/bin/env python3
"""Backtest the USGS river rate-of-rise thresholds against historical events.

Replays the live detector (:mod:`aguayluz.hazard_adapters.river_rise`) over historical
USGS instantaneous values as if it had run every 15 minutes, each run seeing only readings
at least ``--latency-minutes`` old (the GOES relay delay of the live feed), and scores:

* **storm windows** (e.g. Hurricane Fiona): of the NWPS action-stage crossings at sites with
  published thresholds, how many were preceded by a RAPID/FLASH episode *before the
  crossing reading could have arrived*, and by how much (lead over the NWPS flood
  category, which reads the same feed);
* **NWS flash-flood warnings** in ``data/service_events.jsonl``: how many had a RAPID/FLASH
  episode at a stream gauge in a warned municipio during the warning (±2 h);
* **dry-season windows**: RAPID/FLASH episodes per site per 30 days — the nuisance rate,
  since no flood product was issued (an episode there is a sensor fault, a dam release or
  an unwarned local rise, never confirmed by this script).

Promotion is enabled only when the criteria in :data:`CRITERIA` hold; otherwise the
config keeps ``promotion.enabled: false`` and records why. Raw pages are cached under
``--cache-dir`` (never committed).

Usage:
    python scripts/calibrate_river_rise.py --event fiona-2022 --event dry-2026-02 \\
        --state data/river_rise_state.jsonl --cache-dir /tmp/rise-cache --report report.json
    python scripts/calibrate_river_rise.py --all --write-config
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import DATA_DIR  # noqa: E402
from aguayluz.hazard_adapters import river_rise as rr  # noqa: E402

CONTINUOUS = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"
BBOX = "-67.95,17.70,-65.20,18.70"
PROPERTIES = ("monitoring_location_id,parameter_code,statistic_id,time,value,"
              "unit_of_measure,approval_status,qualifier,time_series_id")

#: Fixed windows. NWS warning windows are added from service_events at run time.
EVENTS: dict[str, dict[str, Any]] = {
    "fiona-2022": {"kind": "storm", "start": "2022-09-17T00:00:00Z", "end": "2022-09-20T00:00:00Z",
                   "params": ["00065", "00060"],
                   "note": "Hurricane Fiona: landfall 2022-09-18 19:20Z near Punta Tocón"},
    "maria-2017": {"kind": "storm", "start": "2017-09-19T12:00:00Z", "end": "2017-09-21T12:00:00Z",
                   "params": ["00065", "00060"],
                   "note": "Hurricane María: many gauges failed during the event"},
    "dry-2026-02": {"kind": "quiet", "start": "2026-02-01T00:00:00Z", "end": "2026-02-15T00:00:00Z",
                    "params": ["00065"], "note": "dry season"},
    "dry-2026-03": {"kind": "quiet", "start": "2026-03-01T00:00:00Z", "end": "2026-03-15T00:00:00Z",
                    "params": ["00065"], "note": "dry season"},
}

#: Promotion is enabled only if every criterion holds.
CRITERIA = {
    "storm_hit_rate_min": 0.8,        # rising-limb crossings with an episode open by the NWPS run
    "quiet_episodes_per_site_30d_max": 0.5,
    "min_storm_crossings": 5,         # too few labelled crossings → not enough evidence
}

_EVENT_RE = re.compile(r"event='([^']*)'")


# ------------------------------------------------------------------- acquisition


def _cache_name(pcode: str, day: datetime, page: int) -> str:
    return f"{pcode}_{day:%Y%m%d}_{page}.json"


def fetch_window(pcode: str, start: datetime, end: datetime, cache_dir: Path,
                 *, client: Any = None, max_pages: int = 50) -> list[dict]:
    """Every page of one parameter over [start, end), one day per request, cached."""
    import httpx

    from aguayluz.http_retry import get_with_retry
    from aguayluz.hydromet import USER_AGENT
    from aguayluz.usgs_water_api import api_headers

    cache_dir.mkdir(parents=True, exist_ok=True)
    own = client is None
    client = client or httpx.Client(timeout=120, follow_redirects=True,
                                    headers={"User-Agent": USER_AGENT})
    documents: list[dict] = []
    try:
        day = start
        while day < end:
            stop = min(day + timedelta(days=1), end)
            url: str | None = CONTINUOUS
            params: dict[str, Any] | None = {
                "f": "json", "bbox": BBOX, "parameter_code": pcode, "skipGeometry": "true",
                "properties": PROPERTIES, "limit": 10000,
                "datetime": f"{rr.iso(day)}/{rr.iso(stop)}",
            }
            page = 1
            while url and page <= max_pages:
                cached = cache_dir / _cache_name(pcode, day, page)
                if cached.is_file():
                    doc = json.loads(cached.read_text())
                else:
                    response = get_with_retry(url, params=params, headers=api_headers(), client=client)
                    response.raise_for_status()
                    doc = response.json()
                    cached.write_text(json.dumps(doc))
                documents.append(doc)
                url = next((link.get("href") for link in doc.get("links") or []
                            if link.get("rel") == "next"), None)
                params = None
                page += 1
            day = stop
    finally:
        if own:
            client.close()
    return documents


# ------------------------------------------------------------------------ replay


@dataclass
class Episode:
    site: str
    event_id: str
    onset: datetime
    opened_run: datetime
    peak_class: str
    closed_run: datetime | None = None
    end: datetime | None = None
    revisions: int = 1


@dataclass
class Replay:
    episodes: list[Episode] = field(default_factory=list)
    site_runs: dict[str, int] = field(default_factory=dict)
    runs: int = 0


def _visible(series: list[rr.Observation], times: list[datetime], lo: datetime,
             hi: datetime) -> list[rr.Observation]:
    return series[bisect.bisect_left(times, lo):bisect.bisect_right(times, hi)]


def replay(
    collected: rr.Collected,
    start: datetime,
    end: datetime,
    config: dict[str, Any],
    contexts: dict[str, rr.SiteContext],
    datum: dict[str, str],
    *,
    latency: timedelta = timedelta(minutes=45),
    step: timedelta = timedelta(minutes=15),
) -> Replay:
    """Run the live detector every ``step`` over [start + window, end]."""
    out = Replay()
    classes = rr.promotion_classes(config)
    window = timedelta(hours=float(config["defaults"]["window_hours"]))
    stage_times = {s: [o.time for o in obs] for s, obs in collected.stage.items()}
    q_times = {s: [o.time for o in obs] for s, obs in collected.discharge.items()}
    heads: dict[str, rr.HazardRecord] = {}
    quiet: dict[str, str | None] = {}
    closed_end: dict[str, datetime] = {}
    open_eps: dict[str, Episode] = {}
    now = start + window
    while now <= end:
        out.runs += 1
        for site, series in collected.stage.items():
            context = contexts.get(site) or rr.SiteContext(site)
            settings = rr.site_settings(config, site)
            visible = _visible(series, stage_times[site], now - window, now - latency)
            row = None
            if visible:
                q = collected.discharge.get(site, [])
                q_visible = _visible(q, q_times.get(site, []), now - window, now - latency)
                row = rr.analyse_site(context, visible, q_visible, now, settings,
                                      datum=datum.get(site, "NO_NWPS" if not context.nwps else "NO_COMMON_TIME"))
                out.site_runs[site] = out.site_runs.get(site, 0) + 1
            nb = closed_end.get(site)
            step_ = rr.advance_episode(heads.get(site), row, now, settings, classes,
                                       previous_quiet_since=quiet.get(site),
                                       not_before=nb + timedelta(minutes=15) if nb else None)
            quiet[site] = step_.quiet_since
            if step_.action in {"open", "revise", "close"} and step_.material and step_.event_id:
                latest = rr.parse_time(((row or {}).get("latest") or {}).get("time")) or now
                head = heads.get(site)
                record = rr.episode_record(step_.event_id, step_.material, row or {}, context,
                                           "CALIBRATION", supersedes=head.record_id if head and step_.action != "open" else None,
                                           observed_to=latest,
                                           effective_to=step_.end if step_.action == "close" else None)
                if step_.action == "open":
                    open_eps[site] = Episode(site, step_.event_id, record.observed_from or now, now,
                                             step_.material["peak_class"])
                    out.episodes.append(open_eps[site])
                    heads[site] = record
                elif step_.action == "revise":
                    open_eps[site].peak_class = step_.material["peak_class"]
                    open_eps[site].revisions += 1
                    heads[site] = record
                else:
                    ep = open_eps.pop(site)
                    ep.closed_run, ep.end, ep.peak_class = now, step_.end, step_.material["peak_class"]
                    ep.revisions += 1
                    heads.pop(site, None)
                    closed_end[site] = step_.end or now
        now += step
    return out


# ----------------------------------------------------------------------- scoring


def crossings(series: list[rr.Observation], threshold: float,
              rearm: timedelta = timedelta(hours=6)) -> list[datetime]:
    """Times the stage first reached ``threshold`` after at least ``rearm`` below it."""
    out: list[datetime] = []
    below_since: datetime | None = series[0].time if series and series[0].value < threshold else None
    for obs in series:
        if obs.value < threshold:
            if below_since is None:
                below_since = obs.time
        elif below_since is not None:
            if not out or obs.time - below_since >= rearm:
                out.append(obs.time)
            below_since = None
    return out


def _rise(series: list[rr.Observation], when: datetime, minutes: int) -> float | None:
    tol = timedelta(minutes=10)
    now, before = rr.value_at(series, when, tol), rr.value_at(series, when - timedelta(minutes=minutes), tol)
    return round(now - before, 2) if now is not None and before is not None else None


def crossing_kind(series: list[rr.Observation], crossing: datetime, elevated_1h_ft: float,
                  step_ft: float) -> str:
    """What could be seen before a crossing, from the readings before the crossing reading.

    * ``rising_limb`` — the hour before the crossing reading already rose at least the
      ELEVATED 1-hour threshold: the case a rate-of-rise detector exists for;
    * ``step`` — the crossing reading itself is a jump of at least ``step_ft`` from a stage
      that was not rising: the first anomalous reading *is* the crossing, so no detector
      reading the same feed can precede the NWPS category;
    * ``gradual`` — a slow climb to action stage, which the NWPS category already covers;
    * ``no_data`` — no reading an hour before the crossing (gauge down).
    """
    tol = timedelta(minutes=10)
    before = [o for o in series if o.time < crossing]
    if not before:
        return "no_data"
    last = before[-1]
    hour_ago = rr.value_at(series, last.time - timedelta(minutes=60), tol)
    if hour_ago is None:
        return "no_data"
    if last.value - hour_ago >= elevated_1h_ft:
        return "rising_limb"
    at = rr.value_at(series, crossing, tol)
    if at is not None and at - last.value >= step_ft:
        return "step"
    return "gradual"


def score_storm(result: Replay, collected: rr.Collected, contexts: dict[str, rr.SiteContext],
                datum: dict[str, str], start: datetime, *, latency: timedelta,
                window: timedelta, config: dict[str, Any] | None = None,
                step: timedelta = timedelta(minutes=15),
                lookback: timedelta = timedelta(hours=12)) -> dict[str, Any]:
    """Action-stage crossings, and whether an episode was open by the time NWPS could see them.

    NWPS reads the same feed every 15 minutes, so its category changes on the first scheduled
    run at or after ``crossing + latency``; an episode open by that run is a hit, and the lead
    is how long before that run it opened.
    """
    defaults = (config or rr.load_thresholds())["defaults"]
    elevated = float(defaults["classes"]["ELEVATED_RISE"]["rise_1h_ft"])
    step_ft = float(defaults["spike_ft"])
    first_run = start + window
    labelled: list[dict[str, Any]] = []
    for site, series in collected.stage.items():
        ctx = contexts.get(site)
        action = ((ctx.nwps or {}).get("thresholds") or {}).get("action", {}) if ctx else {}
        stage = action.get("stage") if isinstance(action, dict) else None
        if stage is None or datum.get(site) != "PASS":
            continue
        for crossing in crossings(series, float(stage)):
            if crossing < first_run + latency:
                continue  # inside the warm-up: the replay could not have seen the rise
            seen = crossing + latency
            runs = max(0, -(-int((seen - first_run).total_seconds()) // int(step.total_seconds())))
            visible_run = first_run + runs * step
            active = [e for e in result.episodes if e.site == site and e.opened_run <= visible_run
                      and (e.closed_run is None or (e.end or e.closed_run) >= crossing)]
            first = max(active, key=lambda e: e.opened_run) if active else None
            fresh = first is not None and first.opened_run >= crossing - lookback
            lead = round((visible_run - first.opened_run).total_seconds() / 60) if fresh else None
            labelled.append({
                "site": site, "crossing": rr.iso(crossing), "action_stage_ft": stage,
                "kind": crossing_kind(series, crossing, elevated, step_ft),
                "hit": first is not None, "already_open": first is not None and not fresh,
                "lead_over_nwps_minutes": lead, "ahead_of_nwps": bool(lead and lead > 0),
                "episode_peak": first.peak_class if first else None,
                "rise_1h_ft": _rise(series, crossing, 60), "rise_3h_ft": _rise(series, crossing, 180),
            })
    by_kind: dict[str, dict[str, int]] = {}
    for c in labelled:
        bucket = by_kind.setdefault(c["kind"], {"crossings": 0, "hits": 0, "ahead_of_nwps": 0})
        bucket["crossings"] += 1
        bucket["hits"] += int(c["hit"])
        bucket["ahead_of_nwps"] += int(c["ahead_of_nwps"])
    limb = [c for c in labelled if c["kind"] == "rising_limb"]
    limb_hits = [c for c in limb if c["hit"]]
    leads = [c["lead_over_nwps_minutes"] for c in limb_hits if c["lead_over_nwps_minutes"] is not None]
    return {
        "crossings": len(labelled),
        "hits": sum(1 for c in labelled if c["hit"]),
        "by_kind": dict(sorted(by_kind.items())),
        "rising_limb_crossings": len(limb), "rising_limb_hits": len(limb_hits),
        "rising_limb_hit_rate": round(len(limb_hits) / len(limb), 3) if limb else None,
        "rising_limb_ahead_of_nwps": sum(1 for c in limb if c["ahead_of_nwps"]),
        "lead_over_nwps_minutes_median": statistics.median(leads) if leads else None,
        "lead_over_nwps_minutes_min": min(leads) if leads else None,
        "episodes": len(result.episodes),
        "sites_with_episode": len({e.site for e in result.episodes}),
        "detail": sorted(labelled, key=lambda c: (c["crossing"], c["site"])),
    }


def score_quiet(result: Replay, step: timedelta = timedelta(minutes=15)) -> dict[str, Any]:
    site_days = sum(result.site_runs.values()) * step.total_seconds() / 86400
    per_site: dict[str, int] = {}
    for e in result.episodes:
        per_site[e.site] = per_site.get(e.site, 0) + 1
    rate = len(result.episodes) / (site_days / 30) if site_days else None
    return {
        "episodes": len(result.episodes),
        "site_days": round(site_days, 1),
        "episodes_per_site_30d": round(rate, 3) if rate is not None else None,
        "sites": dict(sorted(per_site.items(), key=lambda kv: -kv[1])),
        "detail": [{"site": e.site, "onset": rr.iso(e.onset), "peak": e.peak_class}
                   for e in sorted(result.episodes, key=lambda e: e.onset)],
    }


def flash_flood_warnings(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """NWS Flash Flood Warnings from service_events, with their warned municipios."""
    out: list[dict[str, Any]] = []
    for event in events:
        match = _EVENT_RE.search(str(event.get("status_text") or ""))
        if not match or match.group(1).strip() != "Flash Flood Warning":
            continue
        start, end = rr.parse_time(event.get("start_time")), rr.parse_time(event.get("end_time"))
        if start is None:
            continue
        areas = [a.strip() for a in str(event.get("affected_area") or "").split(";") if a.strip()]
        out.append({"event_id": event.get("event_id"), "start": start, "end": end or start + timedelta(hours=3),
                    "municipios": [re.sub(r",\s*PR$", "", a).strip() for a in areas]})
    return out


def score_warning(result: Replay, warning: dict[str, Any], municipio_of: dict[str, str],
                  margin: timedelta = timedelta(hours=2)) -> dict[str, Any]:
    from aguayluz.hydromet.spatial import municipio_key

    warned = {municipio_key(m) for m in warning["municipios"]}
    sites = sorted(s for s, m in municipio_of.items() if municipio_key(m) in warned)
    lo, hi = warning["start"] - margin, warning["end"] + margin
    matching = [e for e in result.episodes if e.site in sites and lo <= e.opened_run <= hi + timedelta(minutes=60)]
    return {
        "event_id": warning["event_id"], "start": rr.iso(warning["start"]), "end": rr.iso(warning["end"]),
        "municipios": warning["municipios"], "stream_sites_in_area": sites,
        "sites_with_data": [s for s in sites if result.site_runs.get(s)],
        "corroborated": bool(matching),
        "episodes": [{"site": e.site, "opened_run": rr.iso(e.opened_run), "peak": e.peak_class}
                     for e in matching],
    }


# -------------------------------------------------------------------------- main


def load_contexts(assets_path: Path, nwps_path: Path) -> tuple[dict[str, rr.SiteContext], set[str], dict[str, str]]:
    assets = {}
    for line in assets_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if str(row.get("asset_id", "")).startswith("USGS_"):
            assets[row["asset_id"][5:]] = row
    nwps = {}
    if nwps_path.is_file():
        for line in nwps_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("usgs_id"):
                nwps[str(row["usgs_id"])] = row
    contexts = {site: rr.SiteContext(site, f"USGS_{site}", row.get("asset_name"), row.get("lat"),
                                     row.get("lon"), nwps.get(site))
                for site, row in assets.items()}
    stream = {s for s, row in assets.items() if row.get("asset_subtype") == "stream_gage"}
    municipio = {s: str(row.get("municipality") or "") for s, row in assets.items() if s in stream}
    return contexts, stream, municipio


def load_datum(state_path: Path) -> dict[str, str]:
    """Each site's live datum-check result, from a river_rise_state.jsonl."""
    if not state_path.is_file():
        return {}
    return {str(r["site_no"]): str(r.get("datum_check")) for r in
            (json.loads(line) for line in state_path.read_text(encoding="utf-8").splitlines() if line.strip())}


def evaluate(metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    storm = metrics.get("storm") or {}
    limb = storm.get("rising_limb_crossings") or 0
    if limb < CRITERIA["min_storm_crossings"]:
        reasons.append(f"only {limb} rising-limb storm crossings (< {CRITERIA['min_storm_crossings']})")
    elif (storm.get("rising_limb_hit_rate") or 0) < CRITERIA["storm_hit_rate_min"]:
        reasons.append(f"rising-limb hit rate {storm.get('rising_limb_hit_rate')} "
                       f"< {CRITERIA['storm_hit_rate_min']}")
    quiet = (metrics.get("quiet") or {}).get("episodes_per_site_30d")
    if quiet is None:
        reasons.append("no dry-season window scored")
    elif quiet > CRITERIA["quiet_episodes_per_site_30d_max"]:
        reasons.append(f"dry-season rate {quiet} > {CRITERIA['quiet_episodes_per_site_30d_max']} per site per 30 days")
    return not reasons, reasons


def run_event(event_id: str, spec: dict[str, Any], args: argparse.Namespace, config: dict[str, Any],
              contexts: dict[str, rr.SiteContext], stream: set[str], datum: dict[str, str],
              municipio_of: dict[str, str]) -> dict[str, Any]:
    start, end = rr.parse_time(spec["start"]), rr.parse_time(spec["end"])
    assert start is not None and end is not None
    documents: list[dict] = []
    for pcode in spec.get("params", ["00065"]):
        documents.extend(fetch_window(pcode, start, end, args.cache_dir / event_id))
    defaults = config["defaults"]
    collected = rr.collect(rr.features_of(documents), stream, defaults["excluded_qualifiers"],
                           float(defaults["spike_ft"]))
    latency = timedelta(minutes=args.latency_minutes)
    result = replay(collected, start, end, config, contexts, datum, latency=latency)
    qualifiers: dict[str, int] = {}
    for doc in documents:
        for feature in doc.get("features") or []:
            for q in rr._qualifiers((feature.get("properties") or {}).get("qualifier")):
                qualifiers[q] = qualifiers.get(q, 0) + 1
    summary: dict[str, Any] = {
        "event": event_id, "kind": spec["kind"], "start": spec["start"], "end": spec["end"],
        "note": spec.get("note"), "features": collected.source, "outcomes": collected.outcomes,
        "stream_sites_with_stage": len(collected.stage), "runs": result.runs,
        "qualifiers_seen": dict(sorted(qualifiers.items())),
    }
    window = timedelta(hours=float(defaults["window_hours"]))
    if spec["kind"] == "storm":
        summary["score"] = score_storm(result, collected, contexts, datum, start,
                                       latency=latency, window=window, config=config)
    elif spec["kind"] == "quiet":
        summary["score"] = score_quiet(result)
    else:
        summary["score"] = score_warning(result, spec["warning"], municipio_of)
        summary["score"]["episodes_in_window"] = len(result.episodes)
    return summary


def combine(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    storms = [s["score"] for s in summaries if s["kind"] == "storm"]
    quiet = [s["score"] for s in summaries if s["kind"] == "quiet"]
    warnings = [s["score"] for s in summaries if s["kind"] == "warning"]
    crossings_ = sum(s["crossings"] for s in storms)
    hits = sum(s["hits"] for s in storms)
    limb = sum(s["rising_limb_crossings"] for s in storms)
    limb_hits = sum(s["rising_limb_hits"] for s in storms)
    ahead = sum(s["rising_limb_ahead_of_nwps"] for s in storms)
    by_kind: dict[str, dict[str, int]] = {}
    for s in storms:
        for kind, bucket in s["by_kind"].items():
            total = by_kind.setdefault(kind, {"crossings": 0, "hits": 0, "ahead_of_nwps": 0})
            for key, value in bucket.items():
                total[key] += value
    leads = [c["lead_over_nwps_minutes"] for s in storms for c in s["detail"]
             if c["kind"] == "rising_limb" and c["lead_over_nwps_minutes"] is not None]
    site_days = sum(q["site_days"] for q in quiet)
    q_eps = sum(q["episodes"] for q in quiet)
    return {
        "storm": {"crossings": crossings_, "hits": hits, "by_kind": dict(sorted(by_kind.items())),
                  "rising_limb_crossings": limb, "rising_limb_hits": limb_hits,
                  "rising_limb_hit_rate": round(limb_hits / limb, 3) if limb else None,
                  "rising_limb_ahead_of_nwps": ahead,
                  "lead_over_nwps_minutes_median": statistics.median(leads) if leads else None},
        "quiet": {"episodes": q_eps, "site_days": round(site_days, 1),
                  "episodes_per_site_30d": round(q_eps / (site_days / 30), 3) if site_days else None},
        "flash_flood_warnings": {"warnings": len(warnings),
                                 "with_gauge_data": sum(1 for w in warnings if w["sites_with_data"]),
                                 "corroborated": sum(1 for w in warnings if w["corroborated"])},
    }


def write_config(path: Path, summaries: list[dict[str, Any]], metrics: dict[str, Any],
                 passed: bool, reasons: list[str], latency_minutes: float) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["calibration"] = {
        "status": "CALIBRATED_PASS" if passed else "CALIBRATED_FAIL",
        "method": payload.get("calibration", {}).get("method"),
        "run_at": rr.iso(datetime.now(timezone.utc).replace(microsecond=0)),
        "replay_latency_minutes": latency_minutes,
        "criteria": CRITERIA,
        "events": [{"event": s["event"], "kind": s["kind"], "start": s["start"], "end": s["end"],
                    "stream_sites_with_stage": s["stream_sites_with_stage"]} for s in summaries],
        "metrics": metrics,
        "failed_criteria": reasons,
    }
    payload.setdefault("promotion", {})["enabled"] = bool(passed)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--event", action="append", default=[], help=f"one of {sorted(EVENTS)} or ffw-<event_id>")
    ap.add_argument("--all", action="store_true", help="every fixed window plus every NWS flash-flood warning")
    ap.add_argument("--warnings", action="store_true", help="add every NWS flash-flood warning")
    ap.add_argument("--assets", type=Path, default=DATA_DIR / "utility_assets.jsonl")
    ap.add_argument("--nwps", type=Path, default=DATA_DIR / "nwps_gauge_state.jsonl")
    ap.add_argument("--state", type=Path, default=DATA_DIR / "river_rise_state.jsonl",
                    help="river_rise_state.jsonl whose datum_check results the replay reuses")
    ap.add_argument("--events-file", type=Path, default=DATA_DIR / "service_events.jsonl")
    ap.add_argument("--thresholds", type=Path, default=rr.THRESHOLDS_FILE)
    ap.add_argument("--cache-dir", type=Path, default=Path("calibration-cache"))
    ap.add_argument("--latency-minutes", type=float, default=45.0)
    ap.add_argument("--report", type=Path, help="write the full JSON report here")
    ap.add_argument("--write-config", action="store_true",
                    help="record the result in the thresholds config (and set promotion.enabled)")
    args = ap.parse_args(argv)

    config = rr.load_thresholds(args.thresholds)
    contexts, stream, municipio_of = load_contexts(args.assets, args.nwps)
    datum = load_datum(args.state)
    if not datum:
        print(f"warning: no datum results in {args.state}; headroom scaling and projection are off",
              file=sys.stderr)
    specs: dict[str, dict[str, Any]] = {}
    wanted = list(EVENTS) if args.all else [e for e in args.event if e in EVENTS]
    for event_id in wanted:
        specs[event_id] = EVENTS[event_id]
    if args.all or args.warnings or any(e.startswith("ffw-") for e in args.event):
        service_events = [json.loads(line) for line in args.events_file.read_text().splitlines() if line.strip()] \
            if args.events_file.is_file() else []
        for warning in flash_flood_warnings(service_events):
            event_id = f"ffw-{warning['start']:%Y%m%dT%H%MZ}"
            if args.all or args.warnings or event_id in args.event:
                window = timedelta(hours=float(config["defaults"]["window_hours"]))
                specs[event_id] = {"kind": "warning", "params": ["00065", "00060"],
                                   "start": rr.iso(warning["start"] - window - timedelta(hours=3)),
                                   "end": rr.iso(warning["end"] + timedelta(hours=3)),
                                   "warning": warning, "note": ", ".join(warning["municipios"])}
    unknown = [e for e in args.event if e not in specs]
    if unknown or not specs:
        print(f"unknown or no events: {unknown}; choose from {sorted(EVENTS)} or ffw-<YYYYmmddTHHMMZ>",
              file=sys.stderr)
        return 2

    summaries = [run_event(event_id, spec, args, config, contexts, stream, datum, municipio_of)
                 for event_id, spec in specs.items()]
    metrics = combine(summaries)
    passed, reasons = evaluate(metrics)
    report = {"criteria": CRITERIA, "metrics": metrics, "passed": passed, "failed_criteria": reasons,
              "latency_minutes": args.latency_minutes, "events": summaries}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps({"metrics": metrics, "passed": passed, "failed_criteria": reasons}, indent=2))
    if args.write_config:
        write_config(args.thresholds, summaries, metrics, passed, reasons, args.latency_minutes)
        print(f"recorded in {args.thresholds}: promotion.enabled={passed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
