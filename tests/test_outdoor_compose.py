"""aguayluz.outdoor.compose: the per-municipio outdoor-conditions layer.

Scenarios are built in memory (compose is pure); the last tests run the real ingests
on the recorded fixtures and the CLI end to end.
"""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aguayluz.hazard_plane import HazardFamily, HazardRecord, RecordKind, RecordStatus
from aguayluz.hydromet import store
from aguayluz.models import validate_against_schema
from aguayluz.outdoor import conditions_path, load_municipios, load_reference
from aguayluz.outdoor.compose import STATES, Inputs, compose

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures" / "outdoor"
NOW = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)  # 12:00 AST
MUNICIPIOS = load_municipios()
REFERENCE = load_reference()
REGISTRY = store.load_source_registry()
GEOID = {m["name"]: m["geoid"] for m in MUNICIPIOS}


def receipts(*source_ids, at=NOW, status="PASS"):
    stamp = at.isoformat().replace("+00:00", "Z")
    return {"sources": {s: {"source_id": s, "last_status": status, "last_success_utc": stamp,
                            "last_attempt_utc": stamp} for s in source_ids}}


def make(**kwargs):
    base = dict(municipios=MUNICIPIOS, reference=REFERENCE, registry=REGISTRY, receipts={"sources": {}})
    base.update(kwargs)
    return Inputs(**base)


def by_name(rows):
    return {r["municipio"]: r for r in rows}


def assert_valid(rows):
    assert len(rows) == 78
    for row in rows:
        validate_against_schema("outdoor_condition.v1", row)
        for component in row["components"].values():
            assert component["state"] in STATES


def surf_zone(municipio_names, risk_today="MODERATE", day="2026-10-18"):
    return {
        "zone": "PRZ001", "zone_name": "San Juan and Vicinity PR",
        "municipios": [{"geoid": GEOID[n], "name": n} for n in municipio_names],
        "binding_evidence": "AUTHORITATIVE_BINDING", "binding_method": "srf.including_beaches",
        "issued_at": "2026-10-18T07:30:00Z", "product_id": "p1",
        "periods": [
            {"label": "TODAY", "date": day, "detailed": True, "rip_current_risk": risk_today,
             "surf_min_ft": 4.0, "surf_max_ft": 6.0, "surf_height_text": "4 to 6 feet."},
            {"label": "MONDAY", "date": "2026-10-19", "detailed": True, "rip_current_risk": "LOW",
             "surf_min_ft": 3.0, "surf_max_ft": 3.0, "surf_height_text": "Around 3 feet."},
            {"label": "TUESDAY", "date": "2026-10-20", "detailed": False, "rip_current_risk": None,
             "surf_min_ft": 7.0, "surf_max_ft": 7.0, "surf_height_text": "Surf height around 7 feet."},
        ],
    }


def test_nothing_ingested_is_said_so_and_never_reads_as_benign():
    rows = compose(make(), NOW)
    assert_valid(rows)
    for row in rows:
        assert row["summary"]["level"] == "INSUFFICIENT_DATA"
        assert row["summary"]["drivers"] == []
        states = {c["state"] for c in row["components"].values()}
        assert states <= {"NOT_INGESTED", "NOT_COVERED", "NOT_CONFIGURED"}
    assert by_name(rows)["San Juan"]["components"]["air_quality"]["state"] == "NOT_CONFIGURED"


def test_high_rip_current_today_is_elevated_and_inland_is_not_covered():
    rows = by_name(compose(make(surf=[surf_zone(["San Juan", "Carolina"], "HIGH")],
                                receipts=receipts("nws_surf_zone")), NOW))
    rip = rows["San Juan"]["components"]["rip_current"]
    assert rip["state"] == "REPORTED" and rip["today"]["rip_current_risk"] == "HIGH"
    assert rip["tomorrow"]["rip_current_risk"] == "LOW"
    assert rip["surf_outlook"] == [{"date": "2026-10-20", "surf_min_ft": 7.0, "surf_max_ft": 7.0}]
    assert rip["evidence_class"] == "AUTHORITATIVE_BINDING"
    assert {"component": "rip_current", "level": "ELEVATED",
            "reason": "NWS rip current risk High today"} in rows["San Juan"]["summary"]["drivers"]
    assert rows["Adjuntas"]["components"]["rip_current"]["state"] == "NOT_COVERED"
    # Loíza is coastal, but this product names no beach there: not inferred from San Juan
    assert rows["Loíza"]["components"]["rip_current"]["state"] == "NOT_COVERED"


def test_a_forecast_without_a_period_for_today_is_stale_and_drives_nothing():
    rows = by_name(compose(make(surf=[surf_zone(["San Juan"], "HIGH", day="2026-10-16")],
                                receipts=receipts("nws_surf_zone")), NOW))
    rip = rows["San Juan"]["components"]["rip_current"]
    assert rip["state"] == "STALE"
    assert not [d for d in rows["San Juan"]["summary"]["drivers"] if d["component"] == "rip_current"]
    assert "rip_current" in rows["San Juan"]["summary"]["stale_components"]


def buoy(station, lat, lon, observed_at, wave_ft=3.0):
    return {"station": station, "name": station, "lat": lat, "lon": lon,
            "observed_at": observed_at, "observed": {"wave_height_ft": wave_ft, "water_temp_f": 84.0}}


def test_buoys_attach_by_labelled_proximity_and_go_stale():
    fresh = buoy("41115", 18.376, -67.28, "2026-10-18T15:30:00Z")
    rows = by_name(compose(make(buoys=[fresh], receipts=receipts("ndbc_buoys")), NOW))
    sea = rows["Rincón"]["components"]["sea_state"]
    assert sea["state"] == "REPORTED" and sea["station"] == "41115"
    assert sea["evidence_class"] == "PROXIMITY" and sea["distance_km"] < 10
    assert rows["Adjuntas"]["components"]["sea_state"]["state"] == "NOT_COVERED"  # inland
    assert rows["Fajardo"]["components"]["sea_state"]["state"] == "NOT_COVERED"   # >40 km away
    old = buoy("41115", 18.376, -67.28, "2026-10-18T09:00:00Z")
    rows = by_name(compose(make(buoys=[old], receipts=receipts("ndbc_buoys")), NOW))
    assert rows["Rincón"]["components"]["sea_state"]["state"] == "STALE"


def test_absent_input_carries_the_previous_component_forward_marked():
    previous = compose(make(surf=[surf_zone(["San Juan"])], receipts=receipts("nws_surf_zone")), NOW)
    later = compose(make(receipts=receipts("nws_surf_zone"),
                         previous={r["geoid"]: r for r in previous}), NOW + timedelta(minutes=15))
    rip = by_name(later)["San Juan"]["components"]["rip_current"]
    assert rip["state"] == "REPORTED" and rip["carried_forward"] is True
    assert rip["carried_from"] == "2026-10-18T16:00:00Z"
    assert_valid(later)


def test_nws_land_alerts_bind_through_forecast_zone_names():
    event = {
        "event_id": "AYL_EVT_20261018_NWS-HEAT", "source_ref": "urn:oid:2.49.0.1.840.0.test",
        "affected_area": "San Juan and Vicinity; Northeast",
        "status_text": "event='Heat Advisory' severity=Moderate sender='NWS San Juan PR'",
        "start_time": "2026-10-18T10:00:00-04:00", "end_time": "2026-10-18T17:00:00-04:00",
    }
    flood = {**event, "event_id": "AYL_EVT_20261018_NWS-FLOOD", "affected_area": "Moca, PR; San Sebastian, PR",
             "status_text": "event='Flood Advisory' severity=Minor sender='NWS San Juan PR'"}
    expired = {**event, "event_id": "AYL_EVT_OLD", "end_time": "2026-10-18T09:00:00-04:00"}
    rows = by_name(compose(make(service_events=[event, flood, expired]), NOW))
    sj = rows["San Juan"]["components"]["nws_alerts"]
    assert sj["state"] == "REPORTED" and [a["event"] for a in sj["alerts"]] == ["Heat Advisory"]
    assert "forecast zone" in sj["alerts"][0]["binding_method"]
    assert rows["San Sebastián"]["components"]["nws_alerts"]["alerts"][0]["event"] == "Flood Advisory"
    assert rows["Ponce"]["components"]["nws_alerts"]["state"] == "NONE_ACTIVE"
    assert {"component": "nws_alerts", "level": "CAUTION", "reason": "Heat Advisory"} in rows["San Juan"]["summary"]["drivers"]


def marine_record(zones, status=RecordStatus.ACTIVE, ends=NOW + timedelta(hours=12)):
    return HazardRecord(
        record_id="NWS_MARINE:TJSJ.SC.Y.0042.2026:REV:x", canonical_event_id="NWS_MARINE:TJSJ.SC.Y.0042.2026",
        record_kind=RecordKind.ADVISORY, family=HazardFamily.HYDROMETEOROLOGY,
        hazard_type="MARINE_HAZARD_ADVISORY", source_authority="NWS", source_record_id="urn:x",
        manifestation_id="HYDROMET:nws_marine_alerts:abc", title_raw="Small Craft Advisory",
        status=status, effective_from=NOW - timedelta(hours=1), effective_to=ends,
        normalized_values={"zones": zones},
    )


def test_active_marine_alert_reaches_the_coastal_municipios_of_its_zones():
    rows = by_name(compose(make(hydromet_records=[marine_record(["AMZ742"])],
                                receipts=receipts("nws_marine_alerts")), NOW))
    rincon = rows["Rincón"]["components"]["marine_alerts"]
    assert rincon["state"] == "REPORTED" and rincon["alerts"][0]["event"] == "Small Craft Advisory"
    assert rows["Rincón"]["summary"]["level"] == "ELEVATED"
    assert rows["Ponce"]["components"]["marine_alerts"]["state"] == "NONE_ACTIVE"
    assert rows["Adjuntas"]["components"]["marine_alerts"]["state"] == "NOT_COVERED"
    closed = by_name(compose(make(hydromet_records=[marine_record(["AMZ742"], RecordStatus.TERMINATED)],
                                  receipts=receipts("nws_marine_alerts")), NOW))
    assert closed["Rincón"]["components"]["marine_alerts"]["state"] == "NONE_ACTIVE"


def test_beach_advisories_bind_by_drnas_municipio_text():
    def drna(post, municipio, hazard, beach):
        return HazardRecord(
            record_id=f"DRNA_BEACH:{post}:{beach}:REV:1", canonical_event_id=f"DRNA_BEACH:{post}:{beach}",
            record_kind=RecordKind.ADVISORY, family=HazardFamily.WATER_HEALTH, hazard_type=hazard,
            source_authority="Puerto Rico DRNA", source_record_id=beach, manifestation_id="m",
            title_raw=beach, status=RecordStatus.FINAL, issued_at=NOW - timedelta(days=2),
            raw_attributes={"post_id": post, "municipality_raw": municipio, "beach_name": beach},
        )
    records = [drna("P9", "Loiza", "BEACH_ENTEROCOCCI_BAV_EXCEEDANCE", "Balneario X")]
    rows = by_name(compose(make(hazard_records=records), NOW))
    loiza = rows["Loíza"]["components"]["beach_water_quality"]
    assert loiza["state"] == "REPORTED" and loiza["advisories"][0]["beach"] == "Balneario X"
    assert rows["San Juan"]["components"]["beach_water_quality"]["state"] == "NONE_ACTIVE"
    assert "not a water-quality finding" in rows["San Juan"]["components"]["beach_water_quality"]["note"]
    assert rows["Adjuntas"]["components"]["beach_water_quality"]["state"] == "NOT_COVERED"


def test_air_quality_needs_a_key_then_attaches_by_proximity():
    rows = by_name(compose(make(), NOW))
    assert rows["San Juan"]["components"]["air_quality"]["state"] == "NOT_CONFIGURED"
    aqi = [{"reporting_area": "San Juan", "parameter": "PM10", "aqi": 160, "category": "UNHEALTHY",
            "lat": 18.42, "lon": -66.07, "observed_at": "2026-10-18T15:00:00Z"}]
    rows = by_name(compose(make(aqi=aqi, receipts=receipts("airnow")), NOW))
    air = rows["Guaynabo"]["components"]["air_quality"]
    assert air["state"] == "REPORTED" and air["reporting_area"] == "San Juan" and air["evidence_class"] == "PROXIMITY"
    assert rows["Guaynabo"]["summary"]["level"] == "ELEVATED"
    assert rows["Rincón"]["components"]["air_quality"]["state"] == "NOT_COVERED"


def test_source_that_only_ever_failed_is_source_failed():
    rows = by_name(compose(make(uv=[], receipts={"sources": {"epa_uv": {"last_status": "FAIL"}}}), NOW))
    assert rows["San Juan"]["components"]["uv"]["state"] == "SOURCE_FAILED"


# ------------------------------------------------------------ end to end


def _script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ingested(tmp_path):
    """The real fixtures through the real ingests, at 2026-10-18 12:00 AST."""
    now = "2026-10-18T16:00:00Z"
    common = ["--data-dir", str(tmp_path), "--now", now]
    assert _script("ingest_nws_surf_zone").main(["--src", str(FIX / "srf"), *common]) == 0
    assert _script("ingest_ndbc_buoys").main(["--src", str(FIX / "ndbc_latest_obs.txt"), *common]) == 0
    assert _script("ingest_epa_uv").main(["--src", str(FIX / "epa_uv"), *common]) == 0
    assert _script("ingest_nws_gridpoint_heat").main(["--src", str(FIX / "nws_grid"), *common]) == 0
    assert _script("ingest_nws_marine_alerts").main(["--src", str(FIX / "nws_marine_alerts.json"), *common]) == 0
    return tmp_path


def test_cli_composes_validates_and_does_not_churn(ingested, capsys):
    build = _script("build_outdoor_conditions")
    assert build.main(["--data-dir", str(ingested), "--now", "2026-10-18T16:05:00Z"]) == 0
    rows = by_name(store.read_jsonl(conditions_path(ingested)))
    assert_valid(list(rows.values()))
    assert rows["San Juan"]["components"]["rip_current"]["today"]["rip_current_risk"] == "MODERATE"
    assert rows["San Juan"]["components"]["uv"]["uv_index"] == 10.0
    assert rows["Rincón"]["components"]["sea_state"]["station"] == "41115"
    assert rows["Ponce"]["components"]["uv"]["state"] == "NOT_COVERED"  # no fixture for its ZIP
    before = conditions_path(ingested).read_bytes()
    assert build.main(["--data-dir", str(ingested), "--now", "2026-10-18T16:20:00Z"]) == 0
    assert conditions_path(ingested).read_bytes() == before
    assert "unchanged" in capsys.readouterr().out


def test_cli_rewrites_only_rows_that_changed(ingested):
    build = _script("build_outdoor_conditions")
    assert build.main(["--data-dir", str(ingested), "--now", "2026-10-18T16:05:00Z"]) == 0
    first = by_name(store.read_jsonl(conditions_path(ingested)))
    # 3 h later the buoy reports are stale; inland rows are untouched
    assert build.main(["--data-dir", str(ingested), "--now", "2026-10-18T21:00:00Z"]) == 0
    second = by_name(store.read_jsonl(conditions_path(ingested)))
    assert second["Rincón"]["components"]["sea_state"]["state"] == "STALE"
    assert second["Rincón"]["composed_at"] == "2026-10-18T21:00:00Z"
    assert second["Adjuntas"]["composed_at"] == first["Adjuntas"]["composed_at"] == "2026-10-18T16:05:00Z"
    json.dumps(second)  # serialisable
