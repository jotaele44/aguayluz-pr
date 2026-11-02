"""Read-only V1 API for the AguaYLuz source-intelligence control plane."""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aguayluz.source_intelligence import (
    DOMAIN_REGISTRY,
    NOAA_DIGITAL_COAST_PRODUCTS,
    NOAA_DIGITAL_COAST_ROUTES,
    SOURCE_FAMILIES,
    SOURCE_REQUIREMENTS,
    coverage_report,
)
from aguayluz.source_intelligence.readiness import current_backend_readiness
from aguayluz.source_intelligence.runtime import load_health_receipts
from server.backend import main as legacy

router = APIRouter(prefix="/source-intelligence", tags=["source-intelligence"])

SCOPE_STATEMENT = (
    "Bounded V1 source-family denominator for AguaYLuz domains. "
    "Coverage-matrix readiness is separate from backend qualification, frontend "
    "authorization, and source-universe certification."
)
RUNTIME_ROOT = legacy.DATA / "source_intelligence"


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


def _latest_health(source_family_id: str) -> dict[str, object] | None:
    rows = load_health_receipts(RUNTIME_ROOT, source_family_id)
    if not rows:
        return None
    return max(rows, key=lambda row: str(row.get("checked_at_utc") or ""))


@router.get("/summary")
def source_intelligence_summary() -> JSONResponse:
    coverage = coverage_report()
    readiness = current_backend_readiness(
        coverage_matrix_ready=coverage.coverage_matrix_ready
    )
    return JSONResponse(
        {
            "schema_version": "aguayluz.source-intelligence/v1",
            "api_contract_state": "UNFROZEN",
            "scope": SCOPE_STATEMENT,
            "coverage": coverage.model_dump(mode="json"),
            "coverage_matrix_ready": coverage.coverage_matrix_ready,
            "backend_readiness": {
                "score": readiness.score,
                "states": readiness.states,
                "unresolved": list(readiness.unresolved),
            },
            "backend_readiness_state": (
                "PASS" if readiness.frontend_authorized else "OPEN"
            ),
            "frontend_authorized": readiness.frontend_authorized,
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
        item["runtime_health"] = _latest_health(source.source_family_id)
        item["runtime_health_reason"] = (
            None if item["runtime_health"] else "NO_UNIFIED_RUNTIME_RECEIPT"
        )
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


@router.get("/products")
def source_intelligence_products() -> JSONResponse:
    return JSONResponse(
        {
            "schema_version": "aguayluz.source-intelligence.products/v1",
            "total": len(NOAA_DIGITAL_COAST_PRODUCTS),
            "items": [row.model_dump(mode="json") for row in NOAA_DIGITAL_COAST_PRODUCTS],
        }
    )


@router.get("/routes")
def source_intelligence_routes() -> JSONResponse:
    return JSONResponse(
        {
            "schema_version": "aguayluz.source-intelligence.routes/v1",
            "total": len(NOAA_DIGITAL_COAST_ROUTES),
            "items": [row.model_dump(mode="json") for row in NOAA_DIGITAL_COAST_ROUTES],
        }
    )
