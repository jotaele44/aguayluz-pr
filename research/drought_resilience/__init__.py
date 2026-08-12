"""Design-only drought/resilience P0 reference package."""

from .core import (
    DROUGHT_CLASSES,
    DROUGHT_STATES,
    SUPPLY_NODE_TYPES,
    TrajectoryRule,
    assess_rapid_onset,
    build_drought_state,
    drought_state_to_alert_candidate,
    validate_water_supply_system,
)

__all__ = [
    "DROUGHT_CLASSES",
    "DROUGHT_STATES",
    "SUPPLY_NODE_TYPES",
    "TrajectoryRule",
    "assess_rapid_onset",
    "build_drought_state",
    "drought_state_to_alert_candidate",
    "validate_water_supply_system",
]
