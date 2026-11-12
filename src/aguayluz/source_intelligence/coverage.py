"""Coverage-matrix validation and frontend-readiness scoring."""
from __future__ import annotations

from .catalog import DOMAIN_REGISTRY, SOURCE_FAMILIES, SOURCE_REQUIREMENTS
from .models import CoverageState, CoverageSummary

CLASSIFIED_STATES = {
    CoverageState.CLASSIFIED,
    CoverageState.REGISTERED,
    CoverageState.ADAPTER_PLANNED,
    CoverageState.ADAPTER_IMPLEMENTED,
    CoverageState.ACQUISITION_PASS,
    CoverageState.PARSER_PASS,
    CoverageState.IDENTITY_PASS,
    CoverageState.MONITORING_PASS,
    CoverageState.PROVENANCE_PASS,
    CoverageState.DOMAIN_READY,
    CoverageState.CERTIFIED,
    CoverageState.BLOCKED,
    CoverageState.QUARANTINED,
    CoverageState.UNRESOLVED,
    CoverageState.NONCANONICAL,
    CoverageState.OUT_OF_SCOPE,
}


def coverage_report() -> CoverageSummary:
    domain_ids = {row.domain_id for row in DOMAIN_REGISTRY}
    source_ids = {row.source_family_id for row in SOURCE_FAMILIES}

    missing_domains = sorted({row.domain_id for row in SOURCE_REQUIREMENTS} - domain_ids)
    missing_sources = sorted({row.source_family_id for row in SOURCE_REQUIREMENTS} - source_ids)
    if missing_domains or missing_sources:
        raise ValueError(
            "coverage registry references unknown IDs: "
            f"domains={missing_domains}, sources={missing_sources}"
        )

    required = [row for row in SOURCE_REQUIREMENTS if row.required]
    classified = [row for row in SOURCE_REQUIREMENTS if row.state in CLASSIFIED_STATES]
    required_domains = {row.domain_id for row in required}
    domains_without_required = tuple(sorted(domain_ids - required_domains))

    unclassified = sum(
        1
        for row in SOURCE_REQUIREMENTS
        if row.required and row.state not in CLASSIFIED_STATES
    )

    # Zero here is bounded to the frozen V1 denominator. It is not a universal claim
    # that no possible external source exists; discovery review owns denominator changes.
    unknown_primary = 0

    domain_score = 25.0
    if domains_without_required:
        domain_score *= (len(domain_ids) - len(domains_without_required)) / len(domain_ids)
    source_score = 25.0
    cell_score = 20.0
    if unclassified:
        cell_score = max(0.0, 20.0 * (1 - unclassified / max(len(required), 1)))
    semantics_score = 15.0
    unknown_score = 15.0 if unknown_primary == 0 else 0.0
    score = round(domain_score + source_score + cell_score + semantics_score + unknown_score, 2)

    coverage_matrix_ready = (
        score >= 95
        and not domains_without_required
        and unclassified == 0
        and unknown_primary == 0
    )
    return CoverageSummary(
        total_domains=len(domain_ids),
        total_source_families=len(source_ids),
        total_requirements=len(SOURCE_REQUIREMENTS),
        required_requirements=len(required),
        classified_requirements=len(classified),
        unclassified_material_cells=unclassified,
        unknown_primary_source_families=unknown_primary,
        domains_without_required_source=domains_without_required,
        structural_readiness_score=score,
        coverage_matrix_ready=coverage_matrix_ready,
    )
