"""AguaYLuz source-intelligence control plane.

This package owns source-family coverage, monitoring semantics, immutable source
manifestations, readiness scoring, and adapter contracts. Importing it performs
no network retrieval or entity promotion.
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
from .readiness import BackendReadiness, current_backend_readiness, score_backend_readiness
from .runtime import (
    SourceManifestation,
    freeze_health_receipt,
    load_health_receipts,
    persist_source_manifestation,
    verify_source_manifestation,
)

__all__ = [
    "BackendReadiness",
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
    "SourceManifestation",
    "coverage_report",
    "current_backend_readiness",
    "freeze_health_receipt",
    "load_health_receipts",
    "persist_source_manifestation",
    "score_backend_readiness",
    "verify_source_manifestation",
]
