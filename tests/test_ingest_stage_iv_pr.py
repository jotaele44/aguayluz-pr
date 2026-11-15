"""scripts/ingest_stage_iv_pr.py end to end, offline.

The positive input is the real 2026-10-09 1-day grid in tests/fixtures/stage_iv_pr/.
Shapes NWPS did not publish that day — a heavy-rain day, a re-processed file, a later
data day, a 7-day window, a file whose tag disagrees with its name — are CONSTRUCTED at
test time by rewriting that grid's observation band or tags, and say so.
"""
import importlib.util
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("shapely")

from aguayluz.alert_promotion.hydromet import HydrometInputs, heavy_rain_alerts  # noqa: E402
from aguayluz.hazard_adapters import stage_iv_qpe as adapter  # noqa: E402
from aguayluz.hydromet import store  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
REAL = REPO / "tests" / "fixtures" / "stage_iv_pr" / "nws_precip_1day_20261009_pr.tif"
MUNICIPIOS = 78

_SPEC = importlib.util.spec_from_file_location("ingest_stage_iv_pr", REPO / "scripts" / "ingest_stage_iv_pr.py")
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest  # dataclasses resolve annotations through sys.modules
_SPEC.loader.exec_module(ingest)


def constructed(dest_dir: Path, *, window="1day", day="20261009", scale=1.0, tag_day=None,
                tag_time="12:00:00", bands_kept=4) -> Path:
    """CONSTRUCTED variant of the real grid: observation band × ``scale``, new name/tag,
    optionally only the first ``bands_kept`` bands."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"nws_precip_{window}_{day}_pr.tif"
    with rasterio.open(REAL) as src:
        profile = src.profile
        bands = [src.read(i) for i in range(1, src.count + 1)][:bands_kept]
        tags = src.tags()
        band_tags = [src.tags(i) for i in range(1, src.count + 1)][:bands_kept]
    profile["count"] = len(bands)
    valid = bands[0] > -1e30
    bands[0][valid] = bands[0][valid] * scale
    tags["data_time"] = f"{tag_day or day}T{tag_time}"
    with rasterio.open(out, "w", **profile) as dst:
        for i, band in enumerate(bands, start=1):
            dst.write(band, i)
            dst.update_tags(i, **band_tags[i - 1])
        dst.update_tags(**tags)
    return out


def real_dir(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(REAL, src / REAL.name)
    return src


def run(data_dir, src_dir, day="20261009", *extra, now="2026-10-11T04:00:00Z"):
    return ingest.main(["--src-dir", str(src_dir), "--date", day, "--data-dir", str(data_dir),
                        "--now", now, *extra])


def stage_iv_records(data_dir):
    return [r for r in store.load_records(data_dir) if r.canonical_event_id.startswith(adapter.CANONICAL_PREFIX)]


def test_real_grid_closes_arithmetic_for_every_municipio(tmp_path):
    data = tmp_path / "data"
    assert run(data, real_dir(tmp_path)) == 0
    receipt = store.load_receipts(data)["sources"]["stage_iv_pr"]
    summary = receipt["last_success"]
    assert receipt["last_status"] == "PASS"
    assert summary["arithmetic"] == {
        "source": MUNICIPIOS, "retained": MUNICIPIOS, "excluded": 0, "unresolved": 0,
        "accounted": MUNICIPIOS, "delta": 0, "state": "PASS",
    }
    assert summary["data_date"] == "2026-10-09"
    assert summary["byte_sha256"] == "8ad7d7b0793ea1e3b422b1af26fd163a1a1213c3b754995eaa2d2c46ecd738eb"
    assert summary["windows_missing"] == [
        "nws_precip_last30days_20261009_pr.tif", "nws_precip_last7days_20261009_pr.tif",
    ]
    records = stage_iv_records(data)
    assert len(records) == MUNICIPIOS
    assert all(r.municipality_id and r.normalized_values["cell_count"] >= 1 for r in records)
    aguada = next(r for r in records if r.normalized_values["municipio"] == "Aguada")
    assert aguada.normalized_values["obs_mean_in"] == pytest.approx(1.064, abs=0.001)
    rels = store.load_relationships(data)
    assert len(rels) == MUNICIPIOS
    assert {r.evidence_class.value for r in rels} == {"POINT_IN_POLYGON"}
    assert {r.spatial_state.value for r in rels} == {"FULLY_WITHIN"}
    assert store.integrity(data)["state"] == "PASS"
    snapshot = store.hydromet_paths(data).snapshot_dir("stage_iv_pr") / f"{summary['byte_sha256']}.tif"
    assert snapshot.read_bytes() == REAL.read_bytes()


def test_rerun_is_idempotent_byte_for_byte(tmp_path):
    data, src = tmp_path / "data", real_dir(tmp_path)
    assert run(data, src) == 0
    paths = store.hydromet_paths(data)
    before = {p: p.read_bytes() for p in (paths.records, paths.relationships, paths.manifestations)}
    assert run(data, src, now="2026-10-11T05:00:00Z") == 0
    assert {p: p.read_bytes() for p in before} == before
    assert store.load_receipts(data)["sources"]["stage_iv_pr"]["last_success"]["new_revisions"] == 0


def test_dry_run_writes_nothing(tmp_path, capsys):
    data = tmp_path / "data"
    assert run(data, real_dir(tmp_path), "20261009", "--dry-run") == 0
    assert '"dry_run": true' in capsys.readouterr().out
    assert not data.exists() or not any(data.iterdir())


def test_reprocessed_file_supersedes_the_same_events(tmp_path):
    data = tmp_path / "data"
    assert run(data, real_dir(tmp_path)) == 0
    first = {r.canonical_event_id: r.record_id for r in stage_iv_records(data)}
    reprocessed = constructed(tmp_path / "reprocessed", scale=1.25)  # CONSTRUCTED
    assert run(data, reprocessed.parent) == 0
    current = store.current_by_event(store.load_records(data), adapter.CANONICAL_PREFIX)
    assert set(current) == set(first)
    changed = [r for r in current.values() if r.record_id != first[r.canonical_event_id]]
    assert changed and all(r.supersedes_record_id == first[r.canonical_event_id] for r in changed)
    assert store.integrity(data)["state"] == "PASS"


def test_tag_that_disagrees_with_the_file_date_fails_closed(tmp_path):
    data = tmp_path / "data"
    bad = constructed(tmp_path / "bad", day="20261009", tag_day="20261008")  # CONSTRUCTED
    assert run(data, bad.parent) == 1
    receipt = store.load_receipts(data)["sources"]["stage_iv_pr"]
    assert receipt["last_status"] == "FAIL" and "data_time" in receipt["last_error"]
    assert stage_iv_records(data) == []


def test_window_not_closing_at_12z_fails_closed(tmp_path):
    data = tmp_path / "data"
    midnight = constructed(tmp_path / "midnight", tag_time="00:00:00")  # CONSTRUCTED
    assert run(data, midnight.parent) == 1
    assert "12:00 UTC" in store.load_receipts(data)["sources"]["stage_iv_pr"]["last_error"]


def test_grid_without_the_four_named_bands_fails_closed(tmp_path):
    data = tmp_path / "data"
    two_band = constructed(tmp_path / "two", bands_kept=2)  # CONSTRUCTED: schema change upstream
    assert run(data, two_band.parent) == 1
    assert "expected 4 bands" in store.load_receipts(data)["sources"]["stage_iv_pr"]["last_error"]


def test_percent_of_normal_uses_cells_with_a_prism_normal(tmp_path):
    data = tmp_path / "data"
    assert run(data, real_dir(tmp_path)) == 0
    values = {r.normalized_values["municipio"]: r.normalized_values for r in stage_iv_records(data)}
    # Offshore cells inside a coastal polygon have an observation but no (land) normal.
    assert any(v["paired_cell_count"] < v["cell_count"] for v in values.values())
    for v in values.values():
        assert 0 < v["paired_cell_count"] <= v["cell_count"]
        expected = round(v["obs_mean_paired_in"] / v["normal_mean_in"] * 100, 1)
        # inputs are stored at 1e-3 in, so small normals move the recomputed ratio a little
        assert v["pct_of_normal"] == pytest.approx(expected, rel=0.03, abs=0.5)


def test_one_day_history_outlives_the_closed_heavy_rain_alert():
    from aguayluz.alert_promotion.hydromet import CLOSED_RETENTION, HEAVY_RAIN_FOLLOW_UP

    assert ingest.ONE_DAY_RETENTION >= HEAVY_RAIN_FOLLOW_UP + CLOSED_RETENTION


def test_no_file_writes_a_fail_receipt(tmp_path):
    data, empty = tmp_path / "data", tmp_path / "empty"
    empty.mkdir()
    assert run(data, empty) == 1
    assert store.load_receipts(data)["sources"]["stage_iv_pr"]["last_status"] == "FAIL"


def test_retention_keeps_33_days_of_1day_and_only_the_latest_longer_window(tmp_path):
    data = tmp_path / "data"
    assert run(data, real_dir(tmp_path)) == 0
    src = tmp_path / "later"
    constructed(src, window="last7days", day="20261009")  # CONSTRUCTED
    assert run(data, src) == 0
    constructed(src, window="1day", day="20261020")  # CONSTRUCTED: 11 days later
    constructed(src, window="last7days", day="20261020")  # CONSTRUCTED
    assert run(data, src, "20261020", now="2026-10-21T04:00:00Z") == 0
    days = {(r.normalized_values["window"], r.normalized_values["data_date"]) for r in stage_iv_records(data)}
    assert days == {("1day", "2026-10-09"), ("1day", "2026-10-20"), ("last7days", "2026-10-20")}
    constructed(src, window="1day", day="20261115")  # CONSTRUCTED: 37 days after 10-09
    assert run(data, src, "20261115", now="2026-11-16T04:00:00Z") == 0
    days = {(r.normalized_values["window"], r.normalized_values["data_date"]) for r in stage_iv_records(data)}
    assert ("1day", "2026-10-09") not in days and ("1day", "2026-10-20") in days
    assert store.integrity(data)["state"] == "PASS"


def test_constructed_heavy_rain_day_raises_heavy_rain_alerts(tmp_path):
    data = tmp_path / "data"
    heavy = constructed(tmp_path / "heavy", scale=4.0)  # CONSTRUCTED: real field × 4
    assert run(data, heavy.parent) == 0
    records = store.load_records(data)
    now = datetime(2026, 10, 10, 6, tzinfo=timezone.utc)
    alerts = heavy_rain_alerts(HydrometInputs(records=records, now=now))
    assert alerts, "a ×4 field puts several western municipios over 3 in"
    by_town = {a.municipalities[0]: a for a in alerts}
    assert by_town["Aguada"].severity == 3  # wettest cell 1.606 × 4 ≥ 6 in
    assert all(a.status == "active" and a.alert_id.startswith("AYL_ALR_20261009_qpeheavy_") for a in alerts)
    expected = {
        r.normalized_values["municipio"]
        for r in records
        if adapter.heavy_rain_severity(r.normalized_values) is not None
    }
    assert set(by_town) == expected
    later = heavy_rain_alerts(HydrometInputs(records=records, now=datetime(2026, 10, 13, 13, tzinfo=timezone.utc)))
    assert {a.status for a in later} == {"closed"}


def test_grid_url_matches_the_registry_template():
    source = store.registry_source("stage_iv_pr", store.load_source_registry())
    url = ingest.grid_url(source["endpoints"]["grid"], "1day", date(2026, 10, 9))
    assert url == (
        "https://water.noaa.gov/resources/downloads/precip/stageIV/2026/10/09/"
        "nws_precip_1day_20261009_pr.tif"
    )
