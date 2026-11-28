"""River rate-of-rise promoter (aguayluz.alert_promotion.river_rise).

Episode revision chains are CONSTRUCTED with the adapter's own ``episode_record`` for USGS
50043000 (Río de la Plata at Proyecto La Plata, Aibonito — a real stream gauge bound to
NWPS AIBP4). The NWPS chain is built from the real AIBP4 capture the hydromet promoter
tests use, editing only the category and valid time. Flash-flood warnings are constructed
in the exact ``service_events`` shape ``ingest_nws_alerts.py`` writes.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aguayluz.alert_promotion import GENERATED_MARKERS, build_all_alerts
from aguayluz.alert_promotion.hydromet import HydrometInputs
from aguayluz.alert_promotion.river_rise import (
    CLOSED_RETENTION,
    RIVER_RISE_MARKER,
    flash_flood_windows,
    river_rise_alerts,
)
from aguayluz.alert_validation import validate_alerts
from aguayluz.hazard_adapters import nwps_gauges
from aguayluz.hazard_adapters import river_rise as rr
from aguayluz.impact import build_asset_index

FIXTURES = Path(__file__).parent / "fixtures"
SITE = "50043000"
T0 = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
CTX = rr.SiteContext(SITE, f"USGS_{SITE}", "Rio De La Plata At Proyecto La Plata, Pr", 18.16, -66.228889)


def row(**over) -> dict:
    base = {
        "site_no": SITE, "asset_id": f"USGS_{SITE}", "name": CTX.name,
        "latitude": CTX.latitude, "longitude": CTX.longitude,
        "municipio": "Aibonito", "geoid": "72009", "binding_evidence": "POINT_IN_POLYGON_WITH_ALIAS",
        "data_state": "OK", "rise_class": "RAPID_RISE",
        "latest": {"time": rr.iso(T0 + timedelta(hours=1))},
        "metrics": {"rise_15m_ft": 0.6, "rise_1h_ft": 2.4, "rise_3h_ft": 2.6, "rate_ft_per_h": 2.3},
        "projection": {"to_minor_minutes": None}, "datum_check": "PASS",
    }
    base.update(over)
    return base


def episode(steps: list[tuple[str, float, bool]], *, closed_at: float | None = None,
            minor_at: int | None = None):
    """steps: [(peak_class, hours_after_T0, minor_flag)] → chain, oldest first."""
    event_id = rr.canonical_event_id(SITE, T0)
    chain, head = [], None
    for i, (peak, hours, minor) in enumerate(steps):
        closed = closed_at is not None and i == len(steps) - 1
        material = rr.material_state(SITE, rr.iso(T0), peak, minor, closed)
        r = row(projection={"to_minor_minutes": 35.0} if minor_at == i else {"to_minor_minutes": None})
        head = rr.episode_record(event_id, material, r, CTX, "HYDROMET:usgs_river_rise:x",
                                 supersedes=head.record_id if head else None,
                                 observed_to=T0 + timedelta(hours=hours),
                                 effective_to=T0 + timedelta(hours=closed_at) if closed else None,
                                 municipality_id="72009", binding_evidence="POINT_IN_POLYGON_WITH_ALIAS",
                                 closed_reason="receded" if closed else None)
        chain.append(head)
    return chain


def nwps_chain(steps):
    gauges = json.loads((FIXTURES / "nwps_pr_gauges_sample.json").read_text())["gauges"]
    entry0 = next(g for g in gauges if g["lid"] == "AIBP4")
    detail = nwps_gauges.compact_detail(json.loads((FIXTURES / "nwps_gauge_details" / "AIBP4.json").read_text()))
    records, prev = [], None
    for category, hours in steps:
        entry = copy.deepcopy(entry0)
        entry["status"]["observed"]["floodCategory"] = category
        entry["status"]["observed"]["validTime"] = rr.iso(T0 + timedelta(hours=hours))
        record = nwps_gauges.normalize(entry, detail, "HYDROMET:nwps_gauges:x",
                                       supersedes_record_id=prev.record_id if prev else None)
        records.append(record)
        prev = record
    return records


def ffw(area: str, start_h: float, end_h: float) -> dict:
    local = timezone(timedelta(hours=-4))
    return {
        "event_id": "AYL_EVT_20261007_nws_ffw", "event_type": "unknown",
        "status_text": "event='Flash Flood Warning' severity=Severe sender='NWS San Juan PR'",
        "affected_area": area,
        "start_time": (T0 + timedelta(hours=start_h)).astimezone(local).isoformat(),
        "end_time": (T0 + timedelta(hours=end_h)).astimezone(local).isoformat(),
    }


def inputs(records, *, state=None, promotion=True, now=None, gauge_state=None):
    return HydrometInputs(records=records, gauge_state=gauge_state or [],
                          now=now or T0 + timedelta(hours=2),
                          river_rise_state=[state if state is not None else row()],
                          river_rise_promotion=promotion)


def test_nothing_is_raised_until_calibration_enables_promotion():
    assert river_rise_alerts(inputs(episode([("RAPID_RISE", 1, False)]), promotion=False)) == []
    assert river_rise_alerts(None) == []


def test_uncorroborated_rise_stays_below_critical_and_needs_review():
    (rapid,) = river_rise_alerts(inputs(episode([("RAPID_RISE", 1, False)])))
    assert rapid.alert_id == f"AYL_ALR_20261007{RIVER_RISE_MARKER}{SITE}_1200"
    assert (rapid.severity, rapid.review_status, rapid.status) == (2, "needs_review", "active")
    assert rapid.module_id == "WEATHER_HAZARD" and rapid.evidence_tier == "T2"
    assert rapid.covert_flags == ["watershed_effect"]
    assert rapid.coord_confidence == "exact" and rapid.asset_id == f"USGS_{SITE}"
    assert "Not corroborated" in rapid.validation_notes
    (flash,) = river_rise_alerts(inputs(episode([("RAPID_RISE", 1, False), ("FLASH_RISE", 1.5, False)])))
    assert flash.severity == 3 and flash.review_status == "needs_review"


def test_flash_flood_warning_in_the_same_municipio_corroborates():
    chain = episode([("RAPID_RISE", 1, False), ("FLASH_RISE", 1.5, False)])
    events = [ffw("Aibonito, PR; Cayey, PR", -1, 2)]
    (alert,) = river_rise_alerts(inputs(chain), events)
    assert alert.severity == 4 and alert.review_status == "accepted" and alert.confidence == 75
    assert "Flash Flood Warning for Aibonito, Cayey" in alert.validation_notes
    (rapid,) = river_rise_alerts(inputs(episode([("RAPID_RISE", 1, False)])), events)
    assert rapid.severity == 3  # RAPID + 1 never reaches the critical floor


def test_warning_elsewhere_or_outside_the_episode_does_not_corroborate():
    chain = episode([("FLASH_RISE", 1, False)])
    (other,) = river_rise_alerts(inputs(chain), [ffw("Mayaguez, PR", -1, 2)])
    assert other.severity == 3
    (early,) = river_rise_alerts(inputs(chain), [ffw("Aibonito, PR", -6, -3)])
    assert early.severity == 3
    advisory = dict(ffw("Aibonito, PR", -1, 2), status_text="event='Flood Advisory' severity=Minor")
    (adv,) = river_rise_alerts(inputs(chain), [advisory])
    assert adv.severity == 3


def test_warning_areas_are_parsed_without_the_pr_suffix_and_accents():
    (window,) = flash_flood_windows([ffw("Mayagüez, PR;  Moca, PR", 0, 1)])
    assert window.municipios == ("Mayagüez", "Moca")
    assert "MAYAGUEZ" in window.municipio_keys and "MOCA" in window.municipio_keys
    assert flash_flood_windows([{"status_text": "event='Flash Flood Warning'"}]) == []


def test_nwps_flood_category_at_minor_corroborates_but_action_does_not():
    gauge_state = [{"lid": "AIBP4", "usgs_id": SITE}]
    minor = nwps_chain([("no_flooding", 0), ("minor", 0.75)])
    chain = episode([("FLASH_RISE", 1, False)])
    (alert,) = river_rise_alerts(inputs(chain + minor, gauge_state=gauge_state))
    assert alert.severity == 4
    assert "NWPS gauge AIBP4 at minor" in alert.validation_notes
    action = nwps_chain([("no_flooding", 0), ("action", 0.75)])
    (only_action,) = river_rise_alerts(inputs(chain + action, gauge_state=gauge_state))
    assert only_action.severity == 3


def test_minor_stage_projection_corroborates():
    chain = episode([("RAPID_RISE", 1, False), ("FLASH_RISE", 1.25, True)], minor_at=1)
    (alert,) = river_rise_alerts(inputs(chain))
    assert alert.severity == 4
    assert "minor stage in 35 min" in alert.validation_notes


def test_closed_episode_reports_closed_then_ages_out():
    chain = episode([("RAPID_RISE", 1, False), ("RAPID_RISE", 4, False)], closed_at=3.5)
    (alert,) = river_rise_alerts(inputs(chain, now=T0 + timedelta(days=2)))
    assert alert.status == "closed" and alert.end_at == rr.iso(T0 + timedelta(hours=3.5))
    assert "Closed: receded" in alert.validation_notes
    later = T0 + timedelta(hours=3.5) + CLOSED_RETENTION + timedelta(hours=1)
    assert river_rise_alerts(inputs(chain, now=later)) == []


def test_stale_or_unbound_rise_is_routed_to_review_even_when_corroborated():
    chain = episode([("FLASH_RISE", 1, False)])
    events = [ffw("Aibonito, PR", 0, 2)]
    (stale,) = river_rise_alerts(inputs(chain, state=row(data_state="STALE")), events)
    assert stale.review_status == "needs_review" and "stale" in stale.validation_notes
    unbound = row(municipio=None, candidate_municipio="Cayey", binding_evidence="UNRESOLVED")
    (alert,) = river_rise_alerts(inputs(chain, state=unbound), events)
    assert alert.municipalities == ["Cayey"] and alert.review_status == "needs_review"


def test_alerts_validate_and_register_in_the_engine():
    chain = episode([("RAPID_RISE", 1, False), ("FLASH_RISE", 1.5, True)], minor_at=1)
    alerts = river_rise_alerts(inputs(chain), [ffw("Aibonito, PR", 0, 2)])
    assert alerts and all(r.valid for r in validate_alerts([a.model_dump() for a in alerts]))
    uncorroborated = river_rise_alerts(inputs(episode([("RAPID_RISE", 1, False)])))
    assert all(r.valid for r in validate_alerts([a.model_dump() for a in uncorroborated]))
    assert RIVER_RISE_MARKER in GENERATED_MARKERS
    assets = [json.loads(line) for line in (FIXTURES / "usgs_river_rise" / "utility_assets.jsonl").read_text().splitlines()]
    out = build_all_alerts([ffw("Aibonito, PR", 0, 2)], [], {}, assets, hydromet=inputs(chain))
    rise = [a for a in out if RIVER_RISE_MARKER in a.alert_id]
    assert len(rise) == 1 and f"USGS_{SITE}" in rise[0].linked_asset_ids
    index = build_asset_index(assets)
    (linked,) = river_rise_alerts(inputs(chain), [], None, index)
    assert linked.linked_asset_ids[0] == f"USGS_{SITE}"
