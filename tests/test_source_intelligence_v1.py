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
