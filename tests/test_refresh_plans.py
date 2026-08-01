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
                 refresh.STEP_NEON_PRODUCTS):
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


def test_readings_producers_are_scheduled():
    """Every reading kind the backend serves has a producer in at least one cadence."""
    from server.backend.main import READINGS_FILES  # noqa: PLC0415 — import cost

    producers = {
        "reservoir": "scripts/ingest_usgs_levels.py",
        "groundwater": "scripts/ingest_usgs_groundwater.py",
        "coastal": "scripts/ingest_noaa_tides.py",
        "neon": "scripts/ingest_neon_products.py",
    }
    assert set(READINGS_FILES) == set(producers), (
        "a reading kind with no producer script is a phantom feed in the UI"
    )
    scheduled = {_script_of(s) for plan in refresh.PLANS.values() for s in plan}
    for kind, script in producers.items():
        assert script in scheduled, f"{kind}: {script} is never run by any cadence"
