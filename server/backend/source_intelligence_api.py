"""Read-only V1 API for the AguaYLuz source-intelligence control plane."""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aguayluz.source_intelligence import (
    DOMAIN_REGISTRY,
    SOURCE_FAMILIES,
    SOURCE_REQUIREMENTS,
    coverage_report,
)

router = APIRouter(prefix="/source-intelligence", tags=["source-intelligence"])

SCOPE_STATEMENT = (
    "Bounded V1 source-family denominator for AguaYLuz domains. "
    "Structural frontend readiness does not imply source-universe certification, "
    "live adapter health, or domain certification."
)


def _requirement_index() -> dict[str, list[dict[str, object]]]:
    by_source: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in SOURCE_REQUIREMENTS:
        by_source[row.source_family_id].append(
            {
                "domain_id": row.domain_id,
                "role": row.role.value,
                "required": row.required,
                "adapter_required": row.adapter_required,
                "state": row.state.value,
            }
        )
    return by_source


@router.get("/summary")
def source_intelligence_summary() -> JSONResponse:
    report = coverage_report()
    return JSONResponse(
        {
            "schema_version": "aguayluz.source-intelligence/v1",
            "scope": SCOPE_STATEMENT,
            "coverage": report.model_dump(mode="json"),
            "coverage_matrix_ready": report.coverage_matrix_ready,
            "backend_readiness_state": "OPEN",
            "backend_readiness_reason": (
                "REFERENCE_ADAPTER_ROW_PARSER_AND_UNIFIED_RUNTIME_RECEIPTS_NOT_YET_PASS"
            ),
            "frontend_authorized": False,
            "source_universe_certified": False,
            "domain_certification_complete": False,
        }
    )


@router.get("/domains")
def source_intelligence_domains() -> JSONResponse:
    return JSONResponse(
        {
            "schema_version": "aguayluz.source-intelligence.domains/v1",
            "total": len(DOMAIN_REGISTRY),
            "items": [row.model_dump(mode="json") for row in DOMAIN_REGISTRY],
        }
    )


@router.get("/sources")
def source_intelligence_sources() -> JSONResponse:
    requirements = _requirement_index()
    items = []
    for source in SOURCE_FAMILIES:
        item = source.model_dump(mode="json")
        item["requirements"] = requirements.get(source.source_family_id, [])
        # A source registry entry is not a runtime-health receipt.
        item["runtime_health"] = None
        item["runtime_health_reason"] = "NO_UNIFIED_RUNTIME_RECEIPT"
        items.append(item)
    return JSONResponse(
        {
            "schema_version": "aguayluz.source-intelligence.sources/v1",
            "total": len(items),
            "items": items,
        }
    )


@router.get("/coverage")
def source_intelligence_coverage() -> JSONResponse:
    return JSONResponse(
        {
            "schema_version": "aguayluz.source-intelligence.coverage/v1",
            "summary": coverage_report().model_dump(mode="json"),
            "items": [row.model_dump(mode="json") for row in SOURCE_REQUIREMENTS],
        }
    )
