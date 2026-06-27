"""Shared test fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aguayluz import REPO_ROOT, SCHEMAS_DIR


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def schemas_dir() -> Path:
    return SCHEMAS_DIR


@pytest.fixture
def utility_asset_valid() -> dict:
    return {
        "asset_id": "AYL_AST_LAGO_LA_PLATA_INTAKE",
        "asset_name": "Lago La Plata raw-water intake",
        "asset_type": "water",
        "asset_subtype": "intake",
        "operator": "PRASA",
        "municipality": "Toa Alta",
        "lat": 18.388,
        "lon": -66.232,
        "geometry_type": "point",
        "status": "active",
        "source_ref": "https://api.epa.gov/waters/v1/pointindexing?pgeometry=POINT(-66.232+18.388)",
        "source_hash": None,
        "evidence_tier": "T1",
        "confidence": 70,
        "review_status": "accepted",
        "attribute_coverage": "partial",
        "vpuid": "21",
        "comid": None,
        "reachcode": None,
        "measure": None,
    }


@pytest.fixture
def service_event_valid() -> dict:
    return {
        "event_id": "AYL_EVT_20260606_toa_alta_outage",
        "event_type": "outage",
        "affected_area": "Toa Alta",
        "municipality": "Toa Alta",
        "zone": None,
        "status_text": None,
        "start_time": "2026-06-06T08:00:00Z",
        "end_time": None,
        "reported_customers_or_users": 1200,
        "source_ref": "https://example.gov/notice/2026-06-06",
        "source_hash": None,
        "evidence_tier": "T2",
        "confidence": 55,
        "review_status": "needs_review",
        "linked_asset_ids": ["AYL_AST_LAGO_LA_PLATA_INTAKE"],
    }


@pytest.fixture
def base44_export_valid() -> dict:
    return {
        "module_id": "aguayluz-pr",
        "run_id": "20260606T120000Z_demo",
        "vector": "AGUAYLUZ_WATER_POWER_INFRASTRUCTURE_INTELLIGENCE",
        "status": "PASS",
        "coverage_pct": 100.0,
        "records_total": 1,
        "records_review": 0,
        "records_blocked": 0,
        "confidence_avg": 70.0,
        "source_manifest_path": "outputs/source_manifest.json",
        "integration_report_path": "outputs/integration_report.json",
        "sanitized_summary": "1 PRASA water-intake asset mapped to NHDPlus VPU 21 with partial attribute coverage.",
        "top_findings": [],
        "contradictions": [],
        "gaps": ["StreamCat NLCD attributes unavailable for VPU 21"],
        "next_actions": ["AYL_INGEST_PUBLIC_ASSETS"],
    }


@pytest.fixture
def alert_event_valid() -> dict:
    return {
        "alert_id": "AYL_ALR_20260627_carraizo_001",
        "module_id": "HYDRO_OPS",
        "event_type": "maintenance",
        "status": "draft",
        "source_title": "Trabajos en la represa Carraízo",
        "source_ref": "archive://carraizo_notice_2026-06-27.jpeg",
        "source_hash": None,
        "published_at": None,
        "start_at": "2026-06-27T20:00:00-04:00",
        "end_at": "2026-06-28T02:00:00-04:00",
        "estimated_duration_hr": 6,
        "asset_name": "Represa Carraízo",
        "asset_id": None,
        "operator": "AAA/PRASA",
        "municipalities": ["Carolina", "San Juan", "Trujillo Alto"],
        "sectors_impacted": ["Cupey", "Saint Just"],
        "latitude": 18.344,
        "longitude": -66.01,
        "coord_confidence": "approximate",
        "severity": 2,
        "confidence": 60,
        "ilap_score": 3,
        "covert_flags": ["intake_dependency", "service_area_disruption"],
        "gap_status": "minor",
        "review_status": "needs_review",
        "evidence_tier": "T3",
        "linked_asset_ids": [],
        "validation_notes": "Seed from provided notice image.",
    }


@pytest.fixture
def alert_module_valid() -> dict:
    return {
        "module_id": "HYDRO_OPS",
        "module_name": "Hydro Operations Alerts",
        "sector": "Water",
        "activation_status": "active",
        "priority": "critical",
        "hydro_dependency_relevance": "direct",
        "default_severity_floor": 2,
        "primary_sources": "AAA/PRASA notices",
        "notes": "Reservoir, intake, WTP interruptions.",
    }


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
