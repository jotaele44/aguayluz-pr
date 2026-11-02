"""Read-only V1 API for the AguaYLuz source-intelligence control plane."""
from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aguayluz.source_intelligence import (
    ACQUISITION_ROUTES,
    DOMAIN_REGISTRY,
    SOURCE_FAMILIES,
    SOURCE_PRODUCTS,
    SOURCE_REQUIREMENTS,
    coverage_report,
)
from aguayluz.source_intelligence.readiness import current_backend_readiness
from aguayluz.source_intelligence.route_coverage import route_governance_summary
from aguayluz.source_intelligence.runtime import load_health_receipts

router = APIRouter(prefix="/source-intelligence", tags=["source-intelligence"])

API_SCHEMA_VERSION = "aguayluz.source-intelligence/v1"
API_CONTRACT_CANDIDATE_STATE = "FROZEN_V1_CANDIDATE"
API_CONTRACT_CERTIFIED_STATE = "FROZEN_V1_CERTIFIED"
AUTHORIZED_SHA_ENV = "AGUAYLUZ_SOURCE_INTELLIGENCE_V1_AUTHORIZED_SHA"
BUILD_SHA_ENVS = ("AGUAYLUZ_BUILD_SHA", "VERCEL_GIT_COMMIT_SHA", "GITHUB_SHA")

SCOPE_STATEMENT = (
    "Bounded V1 source-family denominator for AguaYLuz domains. "
    "Coverage-matrix readiness is separate from backend qualification, frontend "
    "authorization, and source-universe certification."
)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_workspace = os.getenv("AGUAYLUZ_DATA_HOME", "").strip()
DATA_ROOT = Path(_workspace) / "data" if _workspace else REPO_ROOT / "data"
RUNTIME_ROOT = DATA_ROOT / "source_intelligence"


def _valid_commit_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{40}", value))


def _current_build_sha() -> str | None:
    for env_name in BUILD_SHA_ENVS:
        value = os.getenv(env_name, "").strip()
        if value and _valid_commit_sha(value):
            return value.lower()
    return None


def _contract_authorization() -> tuple[str, bool, str | None, str | None]:
    build_sha = _current_build_sha()
    authorized_sha = os.getenv(AUTHORIZED_SHA_ENV, "").strip().lower()
    if not _valid_commit_sha(authorized_sha):
        authorized_sha = None
    certified = bool(build_sha and authorized_sha and build_sha == authorized_sha)
    return (
        API_CONTRACT_CERTIFIED_STATE if certified else API_CONTRACT_CANDIDATE_STATE,
        certified,
        authorized_sha,
        build_sha,
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


def _latest_health(source_family_id: str) -> dict[str, object] | None:
    rows = load_health_receipts(RUNTIME_ROOT, source_family_id)
    if not rows:
        return None
    return max(rows, key=lambda row: str(row.get("checked_at_utc") or ""))


@router.get("/summary")
def source_intelligence_summary() -> JSONResponse:
    coverage = coverage_report()
    route_governance = route_governance_summary()
    contract_state, contract_certified, authorized_sha, build_sha = _contract_authorization()
    readiness = current_backend_readiness(
        coverage_matrix_ready=coverage.coverage_matrix_ready,
        api_contract_frozen=contract_certified,
    )
    domain_certification_complete = False
    return JSONResponse(
        {
            "schema_version": API_SCHEMA_VERSION,
            "api_contract_state": contract_state,
            "api_contract_authorized_sha": authorized_sha,
            "build_sha": build_sha,
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
            "route_governance": route_governance.model_dump(mode="json"),
            "source_universe_certified": (
                readiness.frontend_authorized
                and route_governance.route_governance_coverage_complete
                and route_governance.zero_redundant_fetches_certifiable
                and domain_certification_complete
            ),
            "domain_certification_complete": domain_certification_complete,
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
            "total": len(SOURCE_PRODUCTS),
            "items": [row.model_dump(mode="json") for row in SOURCE_PRODUCTS],
        }
    )


@router.get("/routes")
def source_intelligence_routes() -> JSONResponse:
    return JSONResponse(
        {
            "schema_version": "aguayluz.source-intelligence.routes/v1",
            "total": len(ACQUISITION_ROUTES),
            "items": [row.model_dump(mode="json") for row in ACQUISITION_ROUTES],
        }
    )


@router.get("/route-governance")
def source_intelligence_route_governance() -> JSONResponse:
    summary = route_governance_summary()
    return JSONResponse(
        {
            "schema_version": "aguayluz.source-intelligence.route-governance/v1",
            "summary": summary.model_dump(mode="json"),
            "certification_rule": (
                "zero_redundant_fetches_certifiable requires every bounded source family "
                "to have a terminal discovery surface, every payload-bearing product exactly "
                "one canonical payload route, and zero provisional/unresolved product identities"
            ),
        }
    )
