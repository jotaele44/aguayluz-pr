"""The six outdoor-condition ingests end to end, offline.

Positive inputs are real captures under tests/fixtures/outdoor/ (2026-10-18), re-indented
and, for the NWS gridpoints and marine alerts, trimmed. Shapes the sources did not happen
to publish during capture — a High rip current risk, an alert for Puerto Rico waters, a
ZIP whose city disagrees, a failed item — are CONSTRUCTED from those captures and say so.
The AirNow fixtures are constructed from its documented format (see their README).
"""
import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from aguayluz.hydromet import store
from aguayluz.outdoor import load_municipios, state_path

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures" / "outdoor"
GEOID = {m["name"]: m["geoid"] for m in load_municipios()}


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


srf = _load("ingest_nws_surf_zone")
marine = _load("ingest_nws_marine_alerts")
buoys = _load("ingest_ndbc_buoys")
uv = _load("ingest_epa_uv")
heat = _load("ingest_nws_gridpoint_heat")
airnow = _load("ingest_airnow")


def receipt(data_dir, source_id):
    return store.load_receipts(data_dir)["sources"][source_id]


def state(data_dir, source_id):
    return store.read_jsonl(state_path(source_id, data_dir))


# ------------------------------------------------------------------ surf zone


def _srf_dir(tmp_path, transform=None):
    """A copy of the SRF fixtures, optionally with the product text rewritten."""
    target = tmp_path / "srf_src"
    shutil.copytree(FIX / "srf", target, dirs_exist_ok=True)
    if transform:
        product = json.loads((target / "srf_product.json").read_text())
        product["productText"] = transform(product["productText"])
        (target / "srf_product.json").write_text(json.dumps(product))
    return target


def run_srf(data_dir, src, now="2026-10-18T12:00:00Z", *extra):
    return srf.main(["--src", str(src), "--data-dir", str(data_dir), "--now", now, *extra])


def test_surf_zone_closes_arithmetic_and_binds_by_the_products_own_text(tmp_path):
    assert run_srf(tmp_path, FIX / "srf") == 0
    summary = receipt(tmp_path, "nws_surf_zone")["last_success"]
    assert summary["arithmetic"] == {"source": 12, "retained": 10, "excluded": 2, "unresolved": 0,
                                     "accounted": 12, "delta": 0, "state": "PASS"}
    assert summary["outcomes"] == {"excluded:usvi": 2, "retained": 10}
    assert summary["integrity"] == "PASS"
    rows = {r["zone"]: r for r in state(tmp_path, "nws_surf_zone")}
    assert {m["name"] for m in rows["PRZ001"]["municipios"]} == {"Carolina", "San Juan", "Toa Baja"}
    assert rows["PRZ001"]["binding_method"] == "srf.including_beaches"
    # "Rio Grande", "Manati", "Anasco" in the product bind to the accented Census names
    assert {m["name"] for m in rows["PRZ002"]["municipios"]} >= {"Río Grande", "Luquillo"}
    assert rows["PRZ013"]["binding_method"] == "srf.zone_name"
    assert [m["name"] for m in rows["PRZ013"]["municipios"]] == ["Vieques"]
    today = rows["PRZ001"]["periods"][0]
    assert (today["label"], today["date"], today["rip_current_risk"]) == ("TODAY", "2026-10-18", "MODERATE")
    assert (today["surf_min_ft"], today["surf_max_ft"]) == (4.0, 4.0)
    assert not any(z.startswith("VI") for z in rows)
    # two detailed periods (today + tomorrow) per PR zone are records; extended days are not
    records = store.load_records(tmp_path)
    assert len(records) == 20 and all(r.hazard_type == "RIP_CURRENT_RISK" for r in records)
    rels = store.load_relationships(tmp_path)
    assert {r.evidence_class.value for r in rels} == {"AUTHORITATIVE_BINDING"}
    assert store.integrity(tmp_path)["state"] == "PASS"


def test_surf_zone_rerun_writes_no_new_revision(tmp_path):
    assert run_srf(tmp_path, FIX / "srf") == 0
    paths = store.hydromet_paths(tmp_path)
    before = paths.records.read_bytes()
    assert run_srf(tmp_path, FIX / "srf", "2026-10-18T12:15:00Z") == 0
    assert paths.records.read_bytes() == before
    assert receipt(tmp_path, "nws_surf_zone")["last_success"]["new_revisions"] == 0


def test_high_risk_supersedes_the_moderate_forecast(tmp_path):
    """CONSTRUCTED: PRZ001's TODAY risk rewritten from Moderate to High."""
    assert run_srf(tmp_path, FIX / "srf") == 0

    def to_high(text):
        return text.replace("Rip Current Risk*...........Moderate.", "Rip Current Risk*...........High.", 1)

    assert run_srf(tmp_path, _srf_dir(tmp_path, to_high), "2026-10-18T13:00:00Z") == 0
    rows = {r["zone"]: r for r in state(tmp_path, "nws_surf_zone")}
    assert rows["PRZ001"]["periods"][0]["rip_current_risk"] == "HIGH"
    current = store.current_by_event(store.load_records(tmp_path), "NWS_SRF:")
    head = current["NWS_SRF:PRZ001:2026-10-18"]
    assert head.normalized_values["rip_current_risk"] == "HIGH" and head.supersedes_record_id
    assert receipt(tmp_path, "nws_surf_zone")["last_success"]["new_revisions"] == 1


def test_surf_zone_prunes_old_zone_days(tmp_path):
    assert run_srf(tmp_path, FIX / "srf") == 0
    assert run_srf(tmp_path, FIX / "srf", "2026-10-30T12:00:00Z") == 0
    assert store.load_records(tmp_path) == []
    assert store.integrity(tmp_path)["state"] == "PASS"


def test_unparseable_product_is_a_fail_receipt_that_keeps_the_last_success(tmp_path):
    assert run_srf(tmp_path, FIX / "srf") == 0
    broken = _srf_dir(tmp_path)
    (broken / "srf_product.json").write_text('{"productText": 7}')
    assert run_srf(tmp_path, broken, "2026-10-18T13:00:00Z") == 1
    entry = receipt(tmp_path, "nws_surf_zone")
    assert entry["last_status"] == "FAIL" and "unparseable" in entry["last_error"]
    assert entry["last_success_utc"] == "2026-10-18T12:00:00Z"


def test_dry_run_writes_nothing(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    assert run_srf(data, FIX / "srf", "2026-10-18T12:00:00Z", "--dry-run") == 0
    assert list(data.iterdir()) == []
    assert json.loads(capsys.readouterr().out)["arithmetic"]["state"] == "PASS"


# --------------------------------------------------------------- marine alerts


def _pr_alert_doc(*, vtec_action="NEW", message_type="Alert", alert_id="urn:oid:test.pr.1",
                  ends="2026-10-19T06:00:00-04:00"):
    """CONSTRUCTED: the captured Small Craft Advisory re-addressed to Puerto Rico waters."""
    doc = json.loads((FIX / "nws_marine_alerts.json").read_text())
    template = next(f for f in doc["features"] if f["properties"]["event"] == "Small Craft Advisory")
    feature = copy.deepcopy(template)
    props = feature["properties"]
    props.update({
        "id": alert_id, "areaDesc": "Coastal Waters of Northern Puerto Rico out 10 NM",
        "geocode": {"SAME": ["075712"], "UGC": ["AMZ712", "AMZ742"]},
        "senderName": "NWS San Juan PR", "messageType": message_type,
        "sent": "2026-10-18T08:00:00-04:00", "onset": "2026-10-18T08:00:00-04:00",
        "ends": ends, "expires": ends,
    })
    props["parameters"]["VTEC"] = [f"/O.{vtec_action}.TJSJ.SC.Y.0042.261018T1200Z-261019T1000Z/"]
    doc["features"].append(feature)
    return doc


def run_marine(data_dir, doc_or_path, now):
    path = doc_or_path
    if not isinstance(doc_or_path, Path):
        path = data_dir / f"marine_{now[:13]}.json"
        path.write_text(json.dumps(doc_or_path))
    return marine.main(["--src", str(path), "--data-dir", str(data_dir), "--now", now])


def test_marine_alerts_outside_pr_waters_are_excluded(tmp_path):
    assert run_marine(tmp_path, FIX / "nws_marine_alerts.json", "2026-10-18T12:00:00Z") == 0
    summary = receipt(tmp_path, "nws_marine_alerts")["last_success"]
    assert summary["arithmetic"]["retained"] == 0 and summary["arithmetic"]["state"] == "PASS"
    assert summary["outcomes"] == {"excluded:outside_pr_marine_zones": 3}
    assert store.load_records(tmp_path) == []


def test_marine_alert_lifecycle_new_update_close(tmp_path):
    assert run_marine(tmp_path, _pr_alert_doc(), "2026-10-18T12:00:00Z") == 0
    records = store.load_records(tmp_path)
    assert len(records) == 1 and records[0].status.value == "ACTIVE"
    assert records[0].canonical_event_id == "NWS_MARINE:TJSJ.SC.Y.0042.2026"
    assert records[0].normalized_values["zones"] == ["AMZ712", "AMZ742"]
    rels = store.load_relationships(tmp_path)
    assert {r.evidence_class.value for r in rels} == {"PROXIMITY"}
    assert GEOID["San Juan"] in {r.object_id for r in rels} and GEOID["Rincón"] in {r.object_id for r in rels}
    assert GEOID["Ponce"] not in {r.object_id for r in rels}  # south coast: AMZ735, not named

    # an Update under a new CAP id with the same VTEC event and end time is not a revision
    update = _pr_alert_doc(vtec_action="CON", message_type="Update", alert_id="urn:oid:test.pr.2")
    assert run_marine(tmp_path, update, "2026-10-18T15:00:00Z") == 0
    assert len(store.load_records(tmp_path)) == 1

    # gone from the active set -> a TERMINATED revision closes it
    assert run_marine(tmp_path, FIX / "nws_marine_alerts.json", "2026-10-18T18:00:00Z") == 0
    current = store.current_by_event(store.load_records(tmp_path), "NWS_MARINE:")
    head = current["NWS_MARINE:TJSJ.SC.Y.0042.2026"]
    assert head.status.value == "TERMINATED" and head.supersedes_record_id
    assert head.normalized_values["closed_reason"] == "left_active_set"
    assert store.integrity(tmp_path)["state"] == "PASS"

    # closed events past retention are pruned whole
    assert run_marine(tmp_path, FIX / "nws_marine_alerts.json", "2026-11-05T00:00:00Z") == 0
    assert store.load_records(tmp_path) == []


def test_marine_cancel_closes_without_waiting_for_disappearance(tmp_path):
    assert run_marine(tmp_path, _pr_alert_doc(), "2026-10-18T12:00:00Z") == 0
    cancel = _pr_alert_doc(vtec_action="CAN", message_type="Cancel", alert_id="urn:oid:test.pr.3")
    assert run_marine(tmp_path, cancel, "2026-10-18T14:00:00Z") == 0
    head = store.current_by_event(store.load_records(tmp_path), "NWS_MARINE:")["NWS_MARINE:TJSJ.SC.Y.0042.2026"]
    assert head.status.value == "TERMINATED"


# ---------------------------------------------------------------------- buoys


def run_buoys(data_dir, src=FIX / "ndbc_latest_obs.txt", now="2026-10-18T17:30:00Z"):
    return buoys.main(["--src", str(src), "--data-dir", str(data_dir), "--now", now])


def test_buoys_keep_missing_sensors_as_null_never_as_calm(tmp_path):
    assert run_buoys(tmp_path) == 0
    summary = receipt(tmp_path, "ndbc_buoys")["last_success"]
    assert summary["arithmetic"] == {"source": 7, "retained": 5, "excluded": 2, "unresolved": 0,
                                     "accounted": 7, "delta": 0, "state": "PASS"}
    rows = {r["station"]: r for r in state(tmp_path, "ndbc_buoys")}
    assert set(rows) == {"41053", "41056", "41115", "41121", "42085"}
    assert rows["41053"]["raw"]["WVHT"] == "MM"
    assert rows["41053"]["observed"]["wave_height_m"] is None  # not 0.0
    assert rows["41115"]["observed"]["wave_height_m"] == 0.6
    assert rows["41115"]["observed"]["wave_height_ft"] == 2.0
    assert rows["41121"]["observed"]["water_temp_f"] == pytest.approx(86.5, abs=0.1)
    assert rows["41053"]["observed"]["wind_speed_kt"] == pytest.approx(11.7, abs=0.1)
    assert not any(r["stale"] for r in rows.values())
    assert summary["stations_with_wave_height"] == ["41115", "41121"]
    assert store.load_records(tmp_path) == []  # state only


def test_buoy_absent_from_the_feed_is_reported_and_old_reports_are_stale(tmp_path):
    lines = (FIX / "ndbc_latest_obs.txt").read_text().splitlines()
    src = tmp_path / "obs.txt"
    src.write_text("\n".join(ln for ln in lines if not ln.startswith("42085")) + "\n")
    assert run_buoys(tmp_path, src, now="2026-10-19T17:30:00Z") == 0
    summary = receipt(tmp_path, "ndbc_buoys")["last_success"]
    assert summary["stations_missing"] == ["42085"]
    assert all(r["stale"] for r in state(tmp_path, "ndbc_buoys"))


# ------------------------------------------------------------------------- UV


def run_uv(data_dir, src=FIX / "epa_uv", now="2026-10-18T12:00:00Z"):
    return uv.main(["--src", str(src), "--data-dir", str(data_dir), "--now", now])


def test_uv_binds_when_epa_names_the_municipio(tmp_path):
    assert run_uv(tmp_path) == 0
    summary = receipt(tmp_path, "epa_uv")["last_success"]
    assert summary["arithmetic"]["retained"] == 4 and summary["arithmetic"]["state"] == "PASS"
    rows = {r["municipio"]: r for r in state(tmp_path, "epa_uv")}
    assert rows["Humacao"]["uv_index"] == 8.0 and rows["San Juan"]["uv_index"] == 10.0
    assert rows["San Juan"]["uv_category"] == "VERY_HIGH"
    assert {r["binding_evidence"] for r in rows.values()} == {"AUTHORITATIVE_BINDING"}
    assert {r["forecast_date"] for r in rows.values()} == {"2026-10-18"}


def test_uv_city_disagreement_stays_unresolved_and_a_failed_zip_carries_forward(tmp_path):
    assert run_uv(tmp_path) == 0
    src = tmp_path / "uv_src"
    shutil.copytree(FIX / "epa_uv", src)
    # CONSTRUCTED: EPA labels Humacao's ZIP with another city; Adjuntas returns no row.
    humacao = json.loads((src / "uv_00791.json").read_text())
    humacao[0]["CITY"] = "Naguabo"
    (src / "uv_00791.json").write_text(json.dumps(humacao))
    (src / "uv_00601.json").write_text("[]")
    assert run_uv(tmp_path, src, now="2026-10-19T12:00:00Z") == 0
    rows = {r["municipio"]: r for r in state(tmp_path, "epa_uv")}
    assert rows["Humacao"]["binding_evidence"] == "UNRESOLVED"
    assert rows["Adjuntas"]["carried_forward"] is True
    assert rows["Adjuntas"]["retrieved_at"] == "2026-10-18T12:00:00Z"
    summary = receipt(tmp_path, "epa_uv")["last_success"]
    assert summary["arithmetic"]["unresolved"] == 1 and summary["carried_forward"] == ["Adjuntas"]
    assert store.integrity(tmp_path)["state"] == "PASS"  # the carried manifestation is kept


# ----------------------------------------------------------------------- heat


def run_heat(data_dir, src=FIX / "nws_grid", now="2026-10-18T12:00:00Z"):
    return heat.main(["--src", str(src), "--data-dir", str(data_dir), "--now", now])


def test_heat_index_summarised_in_fahrenheit_and_banded(tmp_path):
    assert run_heat(tmp_path) == 0
    summary = receipt(tmp_path, "nws_gridpoint_heat")["last_success"]
    assert summary["arithmetic"]["retained"] == 3 and summary["arithmetic"]["state"] == "PASS"
    rows = {r["municipio"]: r for r in state(tmp_path, "nws_gridpoint_heat")}
    assert set(rows) == {"Adjuntas", "Humacao", "San Juan"}
    for row in rows.values():
        assert row["heat_index_max_f_24h"] >= 70 and row["heat_band_24h"]
        assert row["heat_index_max_f_48h"] >= row["heat_index_max_f_24h"]
        assert row["geometry_precision"] == "REPRESENTATIVE_POINT"
    # the mountain town runs cooler than the coast
    assert rows["Adjuntas"]["heat_index_max_f_24h"] < rows["San Juan"]["heat_index_max_f_24h"]


def test_heat_failed_cell_carries_forward(tmp_path):
    assert run_heat(tmp_path) == 0
    src = tmp_path / "grid_src"
    shutil.copytree(FIX / "nws_grid", src)
    (src / "grid_SJU_107_107.json").write_text('{"properties": {}}')  # CONSTRUCTED
    assert run_heat(tmp_path, src, now="2026-10-18T13:00:00Z") == 0
    rows = {r["municipio"]: r for r in state(tmp_path, "nws_gridpoint_heat")}
    assert rows["Adjuntas"]["carried_forward"] is True
    assert rows["San Juan"]["carried_forward"] is False


# --------------------------------------------------------------------- AirNow


def test_airnow_without_a_key_skips_and_writes_no_receipt(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("AIRNOW_API_KEY", raising=False)
    assert airnow.main(["--data-dir", str(tmp_path)]) == 0
    assert "SKIPPED" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_airnow_offline_dedups_and_never_records_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRNOW_API_KEY", "SECRET-KEY-123")
    assert airnow.main(["--src", str(FIX / "airnow"), "--data-dir", str(tmp_path),
                        "--now", "2026-10-18T18:00:00Z"]) == 0
    summary = receipt(tmp_path, "airnow")["last_success"]
    assert summary["arithmetic"] == {"source": 6, "retained": 3, "excluded": 2, "unresolved": 1,
                                     "accounted": 6, "delta": 0, "state": "PASS"}
    rows = {(r["reporting_area"], r["parameter"]): r for r in state(tmp_path, "airnow")}
    assert rows[("San Juan", "PM10")]["category"] == "UNHEALTHY_FOR_SENSITIVE_GROUPS"
    assert rows[("Ponce", "PM2.5")]["observed_at"] == "2026-10-18T17:00:00Z"  # 13:00 AST
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert b"SECRET-KEY-123" not in path.read_bytes(), path
