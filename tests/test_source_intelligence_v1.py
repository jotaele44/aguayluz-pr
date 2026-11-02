from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from aguayluz.source_intelligence import DOMAIN_REGISTRY, SOURCE_FAMILIES, coverage_report
from aguayluz.source_intelligence.adapters.base import RawArtifact
from aguayluz.source_intelligence.adapters.eia860m import EIA860MAdapter, canonical_month_url
from aguayluz.source_intelligence.health import evaluate_health
from aguayluz.source_intelligence.models import HealthState
from aguayluz.source_intelligence.noaa_digital_coast import (
    NOAA_DIGITAL_COAST_PRODUCTS,
    NOAA_DIGITAL_COAST_ROUTES,
)
from aguayluz.source_intelligence.routes import (
    ArchiveMemberDigest,
    FetchAction,
    FetchPurpose,
    PayloadIdentityClass,
    classify_archive_identity,
    fetch_decision,
    resolve_route,
)


def _minimal_xlsx(*sheet_names: str) -> bytes:
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheets>'
        + "".join(
            f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
            for i, name in enumerate(sheet_names, start=1)
        )
        + '</sheets></workbook>'
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", "<Relationships/>")
    return out.getvalue()


def test_catalog_has_declared_domain_and_source_denominators() -> None:
    assert len(DOMAIN_REGISTRY) == 20
    assert len(SOURCE_FAMILIES) >= 25
    report = coverage_report()
    assert report.total_domains == 20
    assert report.unclassified_material_cells == 0
    assert report.unknown_primary_source_families == 0
    assert report.domains_without_required_source == ()
    assert report.structural_readiness_score >= 95
    assert report.coverage_matrix_ready


def test_health_zero_rows_fails_closed() -> None:
    health = evaluate_health(
        "EIA_860M",
        last_success=datetime.now(timezone.utc),
        record_count=0,
        expected_nonzero=True,
    )
    assert health.state == HealthState.VALIDATION_FAILED
    assert health.error_class == "UNEXPECTED_ZERO_ROWS"


def test_health_staleness_is_independent_of_previous_success() -> None:
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    health = evaluate_health(
        "EIA_860M",
        now=now,
        last_success=now - timedelta(days=60),
        stale_after=timedelta(days=35),
        record_count=20,
    )
    assert health.state == HealthState.STALE


def test_eia860m_url_is_canonical_and_bounded() -> None:
    assert canonical_month_url("march", 2026).endswith(
        "/archive/xls/march_generator2026.xlsx"
    )
    with pytest.raises(ValueError):
        canonical_month_url("smarch", 2026)


def test_eia860m_rejects_html_masquerading_as_xlsx() -> None:
    adapter = EIA860MAdapter()
    artifact = RawArtifact(
        source_family_id="EIA_860M",
        locator="https://example.invalid/march.xlsx",
        content=b"<html>error</html>",
        media_type="text/html",
        retrieved_at_iso="2026-11-02T00:00:00Z",
    )
    with pytest.raises(ValueError):
        adapter.validate_transport(artifact)



def test_eia860m_capabilities_declare_xlsx_transport() -> None:
    capabilities = EIA860MAdapter().capabilities()
    assert capabilities.adapter_id == "eia860m"
    assert capabilities.authentication_class == "NONE"
    assert capabilities.artifact_types == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _member(path: str, size: int, digest: str) -> ArchiveMemberDigest:
    return ArchiveMemberDigest(path=path, uncompressed_size=size, sha256=digest)


def test_noaa_digital_coast_route_registry_is_single_path() -> None:
    product = NOAA_DIGITAL_COAST_PRODUCTS[0]
    payload_routes = [
        route
        for route in NOAA_DIGITAL_COAST_ROUTES
        if route.product_id == product.product_id
        and route.role.value == "CANONICAL_PAYLOAD"
    ]
    assert len(payload_routes) == 1
    assert payload_routes[0].route_id == product.canonical_payload_route_id


def test_full_payload_resolution_prefers_bulk_https() -> None:
    route = resolve_route(
        "NOAA_DC_LIDAR_8630",
        FetchPurpose.FULL_PAYLOAD,
        products=NOAA_DIGITAL_COAST_PRODUCTS,
        routes=NOAA_DIGITAL_COAST_ROUTES,
    )
    assert route.route_id == "NOAA_DC_8630_BULK_HTTPS"
    assert route.may_publish_canonical is True


def test_dav_is_subset_not_competing_canonical_source() -> None:
    route = resolve_route(
        "NOAA_DC_LIDAR_8630",
        FetchPurpose.SUBSET,
        products=NOAA_DIGITAL_COAST_PRODUCTS,
        routes=NOAA_DIGITAL_COAST_ROUTES,
    )
    assert route.route_id == "NOAA_DC_8630_DAV"
    assert route.may_publish_canonical is False


def test_existing_canonical_payload_prevents_redundant_fetch() -> None:
    decision = fetch_decision(
        "NOAA_DC_LIDAR_8630",
        FetchPurpose.FULL_PAYLOAD,
        products=NOAA_DIGITAL_COAST_PRODUCTS,
        routes=NOAA_DIGITAL_COAST_ROUTES,
        existing_representation_route_ids={"NOAA_DC_8630_BULK_HTTPS"},
    )
    assert decision.action == FetchAction.SKIP_USE_EXISTING


def test_fallback_payload_is_used_only_when_canonical_is_unavailable() -> None:
    with pytest.raises(ValueError):
        resolve_route(
            "NOAA_DC_LIDAR_8630",
            FetchPurpose.FULL_PAYLOAD,
            products=NOAA_DIGITAL_COAST_PRODUCTS,
            routes=NOAA_DIGITAL_COAST_ROUTES,
            unavailable_route_ids={"NOAA_DC_8630_BULK_HTTPS"},
        )


def test_archive_identity_pure_recompression() -> None:
    members = (
        _member("a.laz", 100, "a" * 64),
        _member("b.laz", 200, "b" * 64),
    )
    assert classify_archive_identity(
        "1" * 64,
        members,
        "2" * 64,
        members,
    ) == PayloadIdentityClass.PURE_RECOMPRESSION


def test_archive_identity_same_payloads_different_paths() -> None:
    left = (
        _member("left/a.laz", 100, "a" * 64),
        _member("left/b.laz", 200, "b" * 64),
    )
    right = (
        _member("right/x.laz", 200, "b" * 64),
        _member("right/y.laz", 100, "a" * 64),
    )
    assert classify_archive_identity(
        "1" * 64,
        left,
        "2" * 64,
        right,
    ) == PayloadIdentityClass.SAME_PAYLOADS_DIFFERENT_PATHS
