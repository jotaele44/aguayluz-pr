"""Guards on the refresh orchestrator's plans.

The cadences in scripts/refresh.py are the only thing that decides which ingest and
derived-layer scripts ever run. A step whose script was renamed, or a derived layer
ordered before the ingest it reads, fails silently in a scheduled run — so assert the
plans here instead.
"""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

_SPEC = importlib.util.spec_from_file_location(
    "refresh", REPO / "scripts" / "refresh.py"
)
refresh = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(refresh)


def _script_of(step) -> str:
    return step[1][0]


@pytest.mark.parametrize("cadence", sorted(refresh.PLANS))
def test_every_step_script_exists(cadence):
    for step in refresh.PLANS[cadence]:
        assert (REPO / _script_of(step)).is_file(), f"{cadence}: missing {_script_of(step)}"


def test_export_step_script_exists():
    assert (REPO / _script_of(refresh.STEP_EXPORT)).is_file()


@pytest.mark.parametrize("cadence", sorted(refresh.PLANS))
def test_derived_layers_run_last_and_in_dependency_order(cadence):
    """crosswalk -> alert promotion -> alert-system build, after every ingest."""
    scripts = [_script_of(s) for s in refresh.PLANS[cadence]]
    assert scripts[-3:] == [
        "scripts/build_water_power_crosswalk.py",
        "scripts/build_alerts.py",
        "scripts/build_alert_system.py",
    ], f"{cadence} derived layers out of order: {scripts[-3:]}"


def test_alert_system_build_is_blocking():
    """A schema-invalid alert must stop the run before the federation export."""
    optional = refresh.STEP_ALERT_SYSTEM[2]
    assert optional is False


def test_keyed_and_waf_gated_steps_are_optional():
    """Steps that need a credential or a permissioned network path warn and continue."""
    for step in (refresh.STEP_WATERS_ENRICH, refresh.STEP_AEE_FETCH, refresh.STEP_OSHA,
                 refresh.STEP_NEON_PRODUCTS, refresh.STEP_USGS_SAMPLES,
                 refresh.STEP_USGS_FIELD_MEAS, refresh.STEP_USGS_PEAKS, refresh.STEP_NHC):
        assert step[2] is True, f"{_script_of(step)} must be optional"


def test_neon_availability_runs_before_alert_promotion():
    """build_alerts.py reads data/neon_publication_events.jsonl — the NEON ingest that
    writes it has to have run first, or a fresh publication silently misses a cadence."""
    for cadence, plan in refresh.PLANS.items():
        scripts = [_script_of(s) for s in plan]
        if "scripts/ingest_neon.py" not in scripts:
            continue
        assert scripts.index("scripts/ingest_neon.py") < scripts.index("scripts/build_alerts.py"), (
            f"{cadence}: NEON ingest must precede alert promotion"
        )


def test_neon_availability_is_scheduled_daily():
    """The keyless half needs no credential, so there is no reason to run it rarely."""
    assert "scripts/ingest_neon.py" in {_script_of(s) for s in refresh.PLANS["daily"]}


def test_usgs_samples_runs_in_every_cadence():
    """The readings file is gitignored, so it exists only for the life of the job that
    wrote it. Every sibling reading vector is refreshed daily; a weekly-only producer
    would leave this one absent six days in seven."""
    for cadence in ("daily", "weekly", "all"):
        assert "scripts/ingest_usgs_samples.py" in {
            _script_of(s) for s in refresh.PLANS[cadence]
        }, cadence


def test_field_measurements_runs_in_every_non_fast_cadence():
    """Same argument as the samples ingest: the readings file is gitignored and rebuilt
    from empty each run. Absent from `fast` on purpose — a hydrographer visits a well a
    few times a year, so this is not a near-real-time hazard feed."""
    script = "scripts/ingest_usgs_field_measurements.py"
    for cadence in ("daily", "weekly", "all"):
        assert script in {_script_of(s) for s in refresh.PLANS[cadence]}, cadence
    assert script not in {_script_of(s) for s in refresh.PLANS["fast"]}


def test_annual_peaks_are_weekly_not_daily():
    """A peak is published once per water year; there is nothing for a daily run to
    pick up, and the full 1899-> record is ~8,300 rows over 244 sites."""
    script = "scripts/ingest_usgs_peaks.py"
    for cadence in ("weekly", "all"):
        assert script in {_script_of(s) for s in refresh.PLANS[cadence]}, cadence
    for cadence in ("fast", "daily"):
        assert script not in {_script_of(s) for s in refresh.PLANS[cadence]}, cadence


def test_nhc_runs_in_the_fast_cadence_alongside_the_other_hazard_feeds():
    """NHC is the earliest warning in the corpus: NWS publishes a watch once PR is inside
    the forecast envelope, ~48h out; NHC publishes position and intensity from genesis."""
    for cadence in refresh.PLANS:
        assert "scripts/ingest_nhc_storms.py" in {
            _script_of(s) for s in refresh.PLANS[cadence]
        }, cadence


def test_readings_producers_are_scheduled():
    """Every reading kind the backend serves has a producer in at least one cadence."""
    from server.backend.main import READINGS_FILES  # noqa: PLC0415 — import cost

    producers = {
        "reservoir": "scripts/ingest_usgs_levels.py",
        "groundwater": "scripts/ingest_usgs_groundwater.py",
        "coastal": "scripts/ingest_noaa_tides.py",
        "neon": "scripts/ingest_neon_products.py",
        "usgs_field_measurements": "scripts/ingest_usgs_field_measurements.py",
        "usgs_peaks": "scripts/ingest_usgs_peaks.py",
    }
    assert set(READINGS_FILES) == set(producers), (
        "a reading kind with no producer script is a phantom feed in the UI"
    )
    scheduled = {_script_of(s) for plan in refresh.PLANS.values() for s in plan}
    for kind, script in producers.items():
        assert script in scheduled, f"{kind}: {script} is never run by any cadence"
