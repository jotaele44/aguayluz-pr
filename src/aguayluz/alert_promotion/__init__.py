"""Domain-agnostic alert-promotion engine.

The multi-sector alert framework (:mod:`aguayluz.alerts`) ships ten modules, but for
a long time only the water modules had a *generator* turning real ingested signals
into ``AlertEvent`` rows — every other module (SEISMIC_GEO, WEATHER_HAZARD, …) held
only a hand-authored, dormant seed. This package generalises the water pattern in
:mod:`aguayluz.water_alerts` into a registry of per-domain **promoters**, each mapping
already-ingested ``service_events`` / readings into validated ``AlertEvent`` objects.

Promoters (all pure — no I/O, no wall-clock; the CLI ``scripts/build_alerts.py`` does
the I/O):

* water     — :func:`aguayluz.water_alerts.build_water_alerts`  (CONTAMINATION + HYDRO_OPS)
* seismic   — :func:`aguayluz.alert_promotion.seismic.seismic_alerts`   (SEISMIC_GEO)
* weather   — :func:`aguayluz.alert_promotion.weather.weather_alerts`   (WEATHER_HAZARD)

Each promoter stamps a distinct ``alert_id`` marker (``_sdwis_`` / ``_resvlow_`` /
``_seismic_`` / ``_weather_``) so the idempotent merge in the CLI can replace only its
own previously-generated rows while preserving seeds and manual entries.
"""

from __future__ import annotations

from typing import Any

from ..alerts import AlertEvent
from ..water_alerts import build_water_alerts, load_geo
from .seismic import SEISMIC_MARKER, seismic_alerts
from .weather import WEATHER_MARKER, weather_alerts

#: Every alert_id substring that marks a row as machine-generated (safe to replace).
GENERATED_MARKERS: tuple[str, ...] = ("_sdwis_", "_resvlow_", SEISMIC_MARKER, WEATHER_MARKER)

#: Operational-severity floor (0-5 scale) at or above which an alert is life-safety
#: critical and eligible for push / SMS fan-out. Boil-water acute (4), major quake
#: (M5+ -> 4/5) and hurricane/tsunami/tornado warnings (4/5) clear this bar.
CRITICAL_SEVERITY = 4
#: Alert statuses that are no longer actionable (never critical regardless of severity).
_INACTIVE_STATUS = frozenset({"closed", "rejected"})


def is_critical(severity: Any, status: Any = None) -> bool:
    """True when an alert is life-safety critical (drives push/SMS)."""
    try:
        sev = int(severity)
    except (TypeError, ValueError):
        return False
    if status is not None and str(status) in _INACTIVE_STATUS:
        return False
    return sev >= CRITICAL_SEVERITY


def build_all_alerts(
    events: list[dict[str, Any]],
    readings: list[dict[str, Any]] | None,
    geo: dict[str, dict[str, Any]],
    *,
    reservoir_percentile: float = 10.0,
) -> list[AlertEvent]:
    """Run every registered promoter over the ingested signals.

    ``events`` is the full ``data/service_events.jsonl`` set — each promoter filters
    to the event types it owns, so the streams stay decoupled.
    """
    alerts: list[AlertEvent] = []
    alerts.extend(
        build_water_alerts(events, readings, geo, reservoir_percentile=reservoir_percentile)
    )
    alerts.extend(seismic_alerts(events, geo))
    alerts.extend(weather_alerts(events, geo))
    return alerts


__all__ = [
    "GENERATED_MARKERS",
    "CRITICAL_SEVERITY",
    "is_critical",
    "build_all_alerts",
    "build_water_alerts",
    "seismic_alerts",
    "weather_alerts",
    "load_geo",
]
