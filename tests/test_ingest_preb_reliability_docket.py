"""Regression gates for the PREB NEPR-MI-2019-0007 docket index."""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "ingest_preb_reliability_docket",
    REPO / "scripts" / "ingest_preb_reliability_docket.py",
)
preb = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(preb)


HTML = """
<html><body>
<h1>NEPR-MI-2019-0007</h1>
<div>Documentos Publicados: 4</div>
<table>
<tr><th>Documentos</th><th>Fecha</th><th>Orden</th><th>Descargar</th></tr>
<tr>
<td><a href="https://energia.pr.gov/a.pdf">Submission of Monthly Report System Reliability Metrics for July 2026</a>
Asunto: Submission of Monthly Report System Reliability Metrics for July 2026</td>
<td>21/agosto/2026</td><td>2026/08/21</td>
<td><a href="https://energia.pr.gov/a.pdf">Documento</a></td>
</tr>
<tr>
<td><a href="https://energia.pr.gov/b.xlsx">SAIDI_SAIFI_Outage_Data_062021-052022</a>
Asunto: customers outage data</td>
<td>07/noviembre/2022</td><td>2022/11/07</td>
<td><a href="https://energia.pr.gov/b.xlsx">Documento</a></td>
</tr>
<tr>
<td><a href="https://energia.pr.gov/c.pdf">Resolution and Order</a>
Asunto: Requirements of Information Regarding LUMA's FY2025 Performance Metric Data</td>
<td>08/septiembre/2026</td><td>2026/09/08</td>
<td><a href="https://energia.pr.gov/c.pdf">Documento</a></td>
</tr>
<tr>
<td><a href="https://energia.pr.gov/d.xlsx">Motion Submitting Quarterly Report on System Data</a>
Asunto: FY2026-Q3_SAIDI_SAIFI</td>
<td>22/abril/2026</td><td>2026/04/22</td>
<td><a href="https://energia.pr.gov/d.xlsx">Documento</a></td>
</tr>
</table>
</body></html>
"""


def test_docket_parser_closes_advertised_denominator():
    rows, summary = preb.parse_docket(
        HTML,
        preb.DEFAULT_URL,
        "2026-09-19T22:00:00Z",
    )

    assert len(rows) == 4
    assert summary["advertised_document_count"] == 4
    assert summary["parsed_document_count"] == 4
    assert summary["certification_state"] == "PASS"
    assert summary["duplicate_document_url_count"] == 0


def test_raw_strings_and_manifestation_urls_are_preserved():
    rows, _ = preb.parse_docket(
        HTML,
        preb.DEFAULT_URL,
        "2026-09-19T22:00:00Z",
    )
    first = rows[0]

    assert first["title_raw"] == "Submission of Monthly Report System Reliability Metrics for July 2026"
    assert first["subject_raw"] == "Submission of Monthly Report System Reliability Metrics for July 2026"
    assert first["displayed_date_raw"] == "21/agosto/2026"
    assert first["order_date_raw"] == "2026/08/21"
    assert first["document_url"] == "https://energia.pr.gov/a.pdf"


def test_classification_is_discovery_only_and_miluma_noncomparable_by_default():
    rows, _ = preb.parse_docket(
        HTML,
        preb.DEFAULT_URL,
        "2026-09-19T22:00:00Z",
    )
    by_url = {row["document_url"]: row for row in rows}

    assert by_url["https://energia.pr.gov/a.pdf"]["discovery_class"] == "MONTHLY_RELIABILITY_REPORT"
    assert by_url["https://energia.pr.gov/b.xlsx"]["discovery_class"] == "RAW_RELIABILITY_DATA_CANDIDATE"
    assert by_url["https://energia.pr.gov/c.pdf"]["discovery_class"] == "PERFORMANCE_METRICS_REPORT"
    assert by_url["https://energia.pr.gov/d.xlsx"]["discovery_class"] == "PERFORMANCE_METRICS_REPORT"
    assert all(
        row["comparability_to_miluma_live"] == "NONCOMPARABLE_BY_DEFAULT"
        for row in rows
    )


def test_manifestation_id_is_deterministic():
    rows_a, _ = preb.parse_docket(HTML, preb.DEFAULT_URL, "2026-09-19T22:00:00Z")
    rows_b, _ = preb.parse_docket(HTML, preb.DEFAULT_URL, "2026-09-19T23:00:00Z")

    assert [row["manifestation_id"] for row in rows_a] == [
        row["manifestation_id"] for row in rows_b
    ]


def test_partial_parse_fails_closed():
    bad = HTML.replace("Documentos Publicados: 4", "Documentos Publicados: 5")
    with pytest.raises(ValueError, match="denominator mismatch"):
        preb.parse_docket(bad, preb.DEFAULT_URL, "2026-09-19T22:00:00Z")



def test_raw_and_normalized_strings_are_separate():
    html = HTML.replace(
        "Submission of Monthly Report System Reliability Metrics for July 2026",
        "Submission   of Monthly Report  System Reliability Metrics for July 2026",
        1,
    )
    rows, _ = preb.parse_docket(html, preb.DEFAULT_URL, "2026-09-19T22:00:00Z")
    first = rows[0]

    assert "   " in first["title_raw"]
    assert first["title_normalized"] == (
        "Submission of Monthly Report System Reliability Metrics for July 2026"
    )
    assert first["title_raw"] != first["title_normalized"]
