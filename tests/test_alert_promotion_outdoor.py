"""aguayluz.alert_promotion.outdoor: rip current High and PR marine alerts.

Records come from the real ingests run on tests/fixtures/outdoor/, with the High risk
and the Puerto Rico marine alert CONSTRUCTED from those captures (see
tests/test_ingest_outdoor_sources.py for the same construction).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import test_ingest_outdoor_sources as ingests
from aguayluz.alert_promotion import GENERATED_MARKERS, build_all_alerts, is_critical
from aguayluz.alert_promotion.hydromet import HydrometInputs
from aguayluz.alert_promotion.outdoor import outdoor_alerts
from aguayluz.hydromet import store
from aguayluz.water_alerts import load_geo

REPO = Path(__file__).resolve().parent.parent
GEO = load_geo(json.loads((REPO / "data" / "geo" / "pr_municipios.json").read_text())["municipios"])


def _high_srf(tmp_path):
    def to_high(text):
        return text.replace("Rip Current Risk*...........Moderate.", "Rip Current Risk*...........High.", 1)
    return ingests._srf_dir(tmp_path, to_high)


def _inputs(data_dir, now):
    return HydrometInputs(records=store.load_records(data_dir), now=now)


def test_rip_current_high_promotes_below_the_critical_floor(tmp_path):
    assert ingests.run_srf(tmp_path, _high_srf(tmp_path)) == 0
    alerts = outdoor_alerts(_inputs(tmp_path, datetime(2026, 10, 18, 16, tzinfo=timezone.utc)), GEO)
    assert [a.alert_id for a in alerts] == ["AYL_ALR_20261018_ripcurrent_prz001"]
    alert = alerts[0]
    assert alert.module_id == "WEATHER_HAZARD" and alert.status == "active"
    assert alert.severity == 3 and not is_critical(alert.severity, alert.status)
    assert sorted(alert.municipalities) == ["Carolina", "San Juan", "Toa Baja"]
    assert alert.latitude is not None and alert.coord_confidence == "approximate"
    assert "AUTHORITATIVE_BINDING" in alert.validation_notes


def test_moderate_risk_promotes_nothing_and_the_day_closes(tmp_path):
    assert ingests.run_srf(tmp_path, ingests.FIX / "srf") == 0
    assert outdoor_alerts(_inputs(tmp_path, datetime(2026, 10, 18, 16, tzinfo=timezone.utc)), GEO) == []
    assert ingests.run_srf(tmp_path, _high_srf(tmp_path), "2026-10-18T13:00:00Z") == 0
    next_day = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    [alert] = outdoor_alerts(_inputs(tmp_path, next_day), GEO)
    assert alert.status == "closed" and alert.end_at == "2026-10-19T04:00:00Z"


def test_marine_alert_promotes_with_coastal_municipios_then_closes(tmp_path):
    assert ingests.run_marine(tmp_path, ingests._pr_alert_doc(), "2026-10-18T12:00:00Z") == 0
    now = datetime(2026, 10, 18, 13, tzinfo=timezone.utc)
    [alert] = outdoor_alerts(_inputs(tmp_path, now), GEO)
    assert alert.alert_id == "AYL_ALR_20261018_marine_tjsj_sc_y_0042_2026"
    assert alert.status == "active" and alert.severity == 2  # an advisory (VTEC significance Y)
    assert "Rincón" in alert.municipalities and "San Juan" in alert.municipalities
    assert "Ponce" not in alert.municipalities
    assert ingests.run_marine(tmp_path, ingests.FIX / "nws_marine_alerts.json", "2026-10-18T18:00:00Z") == 0
    [closed] = outdoor_alerts(_inputs(tmp_path, datetime(2026, 10, 18, 18, 5, tzinfo=timezone.utc)), GEO)
    assert closed.alert_id == alert.alert_id and closed.status == "closed" and closed.end_at


def test_outdoor_alerts_ride_the_registry_and_the_generated_merge(tmp_path):
    assert ingests.run_srf(tmp_path, _high_srf(tmp_path)) == 0
    hydromet = _inputs(tmp_path, datetime(2026, 10, 18, 16, tzinfo=timezone.utc))
    alerts = build_all_alerts([], [], GEO, [], hydromet=hydromet)
    ids = [a.alert_id for a in alerts if "_ripcurrent_" in a.alert_id]
    assert ids == ["AYL_ALR_20261018_ripcurrent_prz001"]
    assert "_ripcurrent_" in GENERATED_MARKERS and "_marine_" in GENERATED_MARKERS
