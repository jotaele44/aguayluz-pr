"""AguaYLuz source-intelligence control plane.

This package owns source-family coverage, monitoring semantics, and adapter
contracts. Importing it never performs network retrieval or entity promotion.
"""

from .catalog import DOMAIN_REGISTRY, SOURCE_FAMILIES, SOURCE_REQUIREMENTS
from .coverage import coverage_report
from .models import (
    CoverageRole,
    CoverageState,
    DomainDefinition,
    DomainSourceRequirement,
    HealthState,
    MonitoringMode,
    SourceFamilyDefinition,
    SourceHealth,
)

__all__ = [
    "CoverageRole",
    "CoverageState",
    "DOMAIN_REGISTRY",
    "DomainDefinition",
    "DomainSourceRequirement",
    "HealthState",
    "MonitoringMode",
    "SOURCE_FAMILIES",
    "SOURCE_REQUIREMENTS",
    "SourceFamilyDefinition",
    "SourceHealth",
    "coverage_report",
]
