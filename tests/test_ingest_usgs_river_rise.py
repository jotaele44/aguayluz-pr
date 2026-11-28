"""scripts/ingest_usgs_river_rise.py — offline runs through the hydromet plane.

``tests/fixtures/usgs_river_rise/continuous_*.json`` are **real** trimmed captures (see
``test_hazard_adapter_river_rise.py``). The episode lifecycle below is **constructed**:
a synthetic stage history for site 50111315 (a real stream gauge with no NWPS gauge, so
no datum check intervenes) replayed as successive 15-minute runs, each seeing only
readings at least 45 minutes old, like the GOES-relayed live feed.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("shapely")

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "usgs_river_rise"
ASSETS = FIX / "utility_assets.jsonl"
CAPTURE_END = "2026-11-27T00:03:36Z"


def _load():
    spec = importlib.util.spec_from_file_location(
        "ingest_usgs_river_rise", REPO / "scripts" / "ingest_usgs_river_rise.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ingest_usgs_river_rise"] = module
    spec.loader.exec_module(module)
    return module


ingest = _load()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def run(data_dir: Path, src: Path, now: str, *extra: str) -> int:
    return ingest.main(["--src", str(src), "--data-dir", str(data_dir), "--assets", str(ASSETS),
                        "--now", now, *extra])


def state(data_dir: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in (data_dir / "river_rise_state.jsonl").read_text().splitlines()]
    return {r["site_no"]: r for r in rows}


def records(data_dir: Path) -> list[dict]:
    path = data_dir / "hydromet_records.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if "USGS_RISE:" in line]


def receipt(data_dir: Path) -> dict:
    return json.loads((data_dir / "hydromet_receipts.json").read_text())["sources"]["usgs_river_rise"]


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    target.mkdir()
    shutil.copy(FIX / "nwps_gauge_state.jsonl", target / "nwps_gauge_state.jsonl")
    return target


def test_real_capture_runs_offline_and_closes_the_arithmetic(data_dir):
    assert run(data_dir, FIX, CAPTURE_END) == 0
    rows = state(data_dir)
    assert sorted(rows) == ["50043000", "50055000", "50059050", "50111315"]
    la_plata = rows["50043000"]
    assert la_plata["asset_id"] == "USGS_50043000"
    assert la_plata["municipio"] == "Aibonito"
    assert la_plata["binding_evidence"] == "POINT_IN_POLYGON_WITH_ALIAS"
    assert la_plata["nwps"]["lid"] == "AIBP4" and la_plata["nwps"]["thresholds"]["action"] == 15.0
    assert la_plata["datum_check"] == "PASS"
    assert la_plata["rise_class"] == "NONE" and la_plata["data_state"] == "OK"
    assert len(la_plata["series"]["stage_ft"]) == 25
    assert rows["50111315"]["nwps"] is None
    assert rows["50059050"]["site_note"]  # below Carraizo dam
    last = receipt(data_dir)["last_success"]
    assert last["arithmetic"]["state"] == "PASS"
    assert last["outcomes"]["excluded:not_a_stream_site"] > 0  # reservoir + canal
    assert last["integrity"] == "PASS"
    assert last["latency_minutes_p50"] is not None
    assert records(data_dir) == []  # nothing rising, no episode
    snapshots = list((data_dir / "hydromet_snapshots" / "usgs_river_rise").iterdir())
    assert len(snapshots) == 2


def test_dry_run_writes_nothing(data_dir):
    assert run(data_dir, FIX, CAPTURE_END, "--dry-run") == 0
    assert not (data_dir / "river_rise_state.jsonl").exists()
    assert not (data_dir / "hydromet_receipts.json").exists()


def test_missing_response_is_a_fail_receipt_that_keeps_the_last_success(data_dir, tmp_path):
    assert run(data_dir, FIX, CAPTURE_END) == 0
    broken = tmp_path / "broken"
    broken.mkdir()
    shutil.copy(FIX / "continuous_00065.json", broken / "continuous_00065.json")
    assert run(data_dir, broken, "2026-11-27T00:18:36Z") == 1
    entry = receipt(data_dir)
    assert entry["last_status"] == "FAIL" and "continuous_00060.json" in entry["last_error"]
    assert entry["last_success_utc"] == CAPTURE_END


def test_unparseable_response_fails_closed(data_dir, tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "continuous_00065.json").write_text(json.dumps({"type": "FeatureCollection"}))
    shutil.copy(FIX / "continuous_00060.json", bad / "continuous_00060.json")
    assert run(data_dir, bad, CAPTURE_END) == 1
    assert receipt(data_dir)["last_status"] == "FAIL"
    assert not (data_dir / "river_rise_state.jsonl").exists()


def test_stale_snapshots_are_pruned(data_dir):
    folder = data_dir / "hydromet_snapshots" / "usgs_river_rise"
    folder.mkdir(parents=True)
    (folder / ("0" * 64 + ".json")).write_text("{}")
    assert run(data_dir, FIX, CAPTURE_END) == 0
    assert run(data_dir, FIX, "2026-11-27T00:18:36Z") == 0
    names = {p.name.split(".")[0] for p in folder.iterdir()}
    assert "0" * 64 not in names and len(names) == 2


# ----------------------------------------------------------- episode lifecycle

SITE = "50111315"
H0 = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)


def history() -> list[tuple[datetime, float]]:
    """Constructed: 6 h flat at 3.0 ft, +2.4 ft in 1 h, +4.8 ft in the next, then flat."""
    points: list[tuple[datetime, float]] = []
    stage = 3.0
    for i in range(24 * 4):
        t = H0 + timedelta(minutes=15 * i)
        if 24 < i <= 28:
            stage += 0.6
        elif 28 < i <= 32:
            stage += 1.2
        points.append((t, round(stage, 2)))
    return points


def write_src(folder: Path, now: datetime, points: list[tuple[datetime, float]]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    visible = [(t, v) for t, v in points if now - timedelta(hours=6) <= t <= now - timedelta(minutes=45)]
    features = [{"type": "Feature", "geometry": None, "properties": {
        "monitoring_location_id": f"USGS-{SITE}", "parameter_code": "00065", "statistic_id": "00011",
        "time": t.isoformat(), "value": str(v), "unit_of_measure": "ft",
        "approval_status": "Provisional", "qualifier": None, "time_series_id": "constructed"}}
        for t, v in visible]
    (folder / "continuous_00065.json").write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    (folder / "continuous_00060.json").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    return folder


def replay(data_dir: Path, tmp_path: Path, visible_hours: list[float]) -> list[dict]:
    """One run per visible-data hour; returns each run's state row for SITE."""
    out = []
    points = history()
    for n, hours in enumerate(visible_hours):
        now = H0 + timedelta(hours=hours, minutes=45)
        src = write_src(tmp_path / f"run{n}", now, points)
        assert run(data_dir, src, _iso(now)) == 0
        out.append(state(data_dir)[SITE])
    return out


def test_rise_opens_escalates_and_closes_one_episode(data_dir, tmp_path):
    rows = replay(data_dir, tmp_path, [6, 7, 7, 8, 9, 10, 11, 11.5, 12, 12.5])
    assert [r["rise_class"] for r in rows[:4]] == ["NONE", "RAPID_RISE", "RAPID_RISE", "FLASH_RISE"]
    revisions = records(data_dir)
    events = {r["canonical_event_id"] for r in revisions}
    assert len(events) == 1
    (event_id,) = events
    assert event_id == "USGS_RISE:50111315:20260901T0600Z"  # the low point before the rise
    # open (RAPID) → escalate (FLASH) → close; the repeated hour-7 run added nothing.
    kinds = [(r["normalized_values"]["peak_class"], r["status"]) for r in revisions]
    assert kinds == [("RAPID_RISE", "ACTIVE"), ("FLASH_RISE", "ACTIVE"), ("FLASH_RISE", "TERMINATED")]
    opened, escalated, closed = revisions
    assert escalated["supersedes_record_id"] == opened["record_id"]
    assert closed["supersedes_record_id"] == escalated["record_id"]
    assert closed["normalized_values"]["closed_reason"] == "receded"
    assert closed["effective_to"] is not None
    assert opened["normalized_values"]["series"]["stage_ft"][-1] is not None
    assert "series" not in escalated["normalized_values"]
    assert opened["municipality_id"] and opened["facility_id"] == "USGS_50111315"
    # While open, the state row names the episode; the quiet clock starts at hour 11.
    assert rows[3]["episode"]["peak_class"] == "FLASH_RISE"
    assert rows[6]["quiet_since"] == "2026-09-01T11:00:00Z"
    assert rows[-1]["episode"] is None and rows[-1]["quiet_since"] is None
    rels = [json.loads(line) for line in (data_dir / "hydromet_relationships.jsonl").read_text().splitlines()]
    preds = {(r["predicate"], r["object_kind"]) for r in rels if r["subject_id"] == opened["record_id"]}
    assert preds == {("SAME_LOCATION", "FACILITY"), ("SPATIALLY_INTERSECTS", "MUNICIPALITY")}


def test_closed_episodes_are_pruned_after_retention(data_dir, tmp_path):
    replay(data_dir, tmp_path, [6, 7, 8, 9, 10, 11, 11.5, 12, 12.5])
    assert records(data_dir)
    later = H0 + timedelta(days=40)
    flat = [(later - timedelta(minutes=15 * i), 3.0) for i in range(30)]
    assert run(data_dir, write_src(tmp_path / "later", later, flat), _iso(later)) == 0
    assert records(data_dir) == []
    assert receipt(data_dir)["last_success"]["events_pruned"] == 1


def test_offline_multi_page_responses_are_all_read(data_dir, tmp_path):
    src = tmp_path / "paged"
    src.mkdir()
    doc = json.loads((FIX / "continuous_00065.json").read_text())
    half = len(doc["features"]) // 2
    (src / "continuous_00065.json").write_text(json.dumps({**doc, "features": doc["features"][:half]}))
    (src / "continuous_00065_p2.json").write_text(json.dumps({**doc, "features": doc["features"][half:]}))
    shutil.copy(FIX / "continuous_00060.json", src / "continuous_00060.json")
    assert run(data_dir, src, CAPTURE_END) == 0
    last = receipt(data_dir)["last_success"]
    assert [r["key"] for r in last["responses"]] == [
        "continuous_00065.json", "continuous_00065_p2.json", "continuous_00060.json"]
    paged = state(data_dir)["50043000"]["metrics"]

    other = tmp_path / "other"
    other.mkdir()
    assert run(other, FIX, CAPTURE_END) == 0
    assert state(other)["50043000"]["metrics"] == paged
