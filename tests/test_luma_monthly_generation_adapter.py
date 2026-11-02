from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "luma_monthly_generation_adapter",
    REPO / "scripts" / "luma_monthly_generation_adapter.py",
)
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
assert SPEC.loader is not None
SPEC.loader.exec_module(adapter)


def test_parse_index_builds_authoritative_entries_and_preserves_multiple_manifestations():
    html = """
    <html><body>
      <a href="/so_document/january-2023-monthly-generation-performance-report/">
        January 2023 Monthly Generation Performance Report
      </a>
      <a href="/so_document/january-2023-monthly-generation-performance-report-corrected/">
        January 2023 Monthly Generation Performance Report
      </a>
      <a href="/so_document/march-2023-monthly-generation-performance-report/">
        March 2023 Monthly Generation Performance Report
      </a>
    </body></html>
    """
    rows = adapter.parse_index_entries(html, "https://lumapr.com/monitoreo-de-bps/")
    assert [(r.period, r.href) for r in rows] == [
        (
            "2023-01",
            "https://lumapr.com/so_document/january-2023-monthly-generation-performance-report-corrected/",
        ),
        (
            "2023-01",
            "https://lumapr.com/so_document/january-2023-monthly-generation-performance-report/",
        ),
        (
            "2023-03",
            "https://lumapr.com/so_document/march-2023-monthly-generation-performance-report/",
        ),
    ]
    assert all(r.discovery_class == "AUTHORITATIVE_INDEX_ENTRY" for r in rows)


def test_index_denominator_fails_closed_on_missing_month():
    entries = [
        adapter.DiscoveryEntry(
            period="2023-01",
            href="https://example.test/jan/",
            title_raw="January 2023 Monthly Generation Performance Report",
            index_url="https://example.test/index/",
        ),
        adapter.DiscoveryEntry(
            period="2023-03",
            href="https://example.test/mar/",
            title_raw="March 2023 Monthly Generation Performance Report",
            index_url="https://example.test/index/",
        ),
    ]
    expected = adapter.expected_periods_from_index(entries, adapter.Period.parse("2023-01"))
    assert [str(p) for p in expected] == ["2023-01", "2023-02", "2023-03"]
    result = adapter.index_denominator(entries, expected)
    assert result["gate"] == "FAIL_CLOSED"
    assert result["missing_periods"] == ["2023-02"]


def test_synthesized_url_is_discovery_only_pattern():
    assert adapter.synthesized_landing_url(adapter.Period(2026, 1)) == (
        "https://lumapr.com/so_document/"
        "january-2026-monthly-generation-performance-report/"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hydro Total Generation 1,886.90 MWh", "HYDRO_MWH_PRESENT"),
        ("Hydro generation 15.6 MW", "HYDRO_MW_ONLY"),
        ("Hydro availability 29%", "HYDRO_OTHER_METRIC"),
        ("Solar generation 42 MWh", "HYDRO_ABSENT"),
    ],
)
def test_hydro_classification_keeps_measurement_types_distinct(text, expected):
    assert adapter.classify_hydro_text(text) == expected


def test_unit_parser_does_not_confuse_mw_and_mwh():
    units = adapter.classify_units("Hydro: 15 MW; net generation 1,886.90 MWh; CF 29%")
    assert units == {"MW", "MWH", "%"}


def test_typed_observation_is_never_canonical_identity_from_name_only():
    rows = adapter.typed_observations(
        "2026-06",
        4,
        "Caonillas\nNet Generation\n1,886.90 MWh",
        "a" * 64,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["normalized_value"] == pytest.approx(1886.90)
    assert row["normalized_unit"] == "MWH"
    assert row["measurement_class"] == "ENERGY"
    assert row["identity_state"] == "CANDIDATE_NOT_IDENTITY"
    assert row["canonical_promotion_eligible"] is False


def test_incremental_selects_latest_changed_and_unresolved_periods():
    expected = [adapter.Period(2026, m) for m in range(1, 7)]
    index_map = {
        "2026-01": [
            adapter.DiscoveryEntry(
                "2026-01",
                "https://example.test/jan-new/",
                "January 2026 Monthly Generation Performance Report",
                "https://example.test/index/",
            )
        ],
        **{
            f"2026-{m:02d}": [
                adapter.DiscoveryEntry(
                    f"2026-{m:02d}",
                    f"https://example.test/{m}/",
                    "",
                    "https://example.test/index/",
                )
            ]
            for m in range(2, 7)
        },
    }
    prior = []
    for m in range(1, 7):
        prior.append(
            {
                "period": f"2026-{m:02d}",
                "indexed_href": (
                    "https://example.test/jan-old/" if m == 1 else f"https://example.test/{m}/"
                ),
                "source_state": "PASS" if m != 3 else "SOURCE_UNAVAILABLE",
            }
        )
    selected = adapter.select_incremental_periods(expected, index_map, prior, latest_n=2)
    assert [str(p) for p in selected] == ["2026-01", "2026-03", "2026-05", "2026-06"]


def test_relation_to_prior_classifies_byte_and_manifestation_identity():
    prior = [
        {
            "period": "2026-01",
            "pdf_url": "https://example.test/a.pdf",
            "sha256": "abc",
        }
    ]
    assert adapter.relation_to_prior("2026-01", "https://example.test/a.pdf", "abc", prior) == "BYTE_IDENTICAL"
    assert (
        adapter.relation_to_prior("2026-01", "https://example.test/b.pdf", "abc", prior)
        == "SOURCE_MANIFESTATION_CHANGE_PAYLOAD_IDENTICAL"
    )
    assert (
        adapter.relation_to_prior("2026-01", "https://example.test/a.pdf", "def", prior)
        == "NEW_MANIFESTATION_SAME_URL_DIFFERENT_BYTES"
    )


def test_reconcile_keeps_distinct_payloads_and_replaces_same_manifestation_key_by_latest():
    base = {
        "schema_version": adapter.SCHEMA_VERSION,
        "period": "2026-01",
        "manifestation_key": "same",
        "retrieval_utc": "2026-01-01T00:00:00Z",
        "pdf_url": "https://example.test/a.pdf",
        "sha256": "aaa",
    }
    newer = {**base, "retrieval_utc": "2026-01-02T00:00:00Z", "notes": ["new"]}
    other = {
        **base,
        "manifestation_key": "other",
        "pdf_url": "https://example.test/b.pdf",
        "sha256": "bbb",
    }
    rows = adapter.reconcile_manifest_rows([base, newer, other])
    assert len(rows) == 2
    by_key = {r["manifestation_key"]: r for r in rows}
    assert by_key["same"]["retrieval_utc"] == "2026-01-02T00:00:00Z"
    assert by_key["other"]["sha256"] == "bbb"


def test_duplicate_period_state_distinguishes_payload_and_url_changes():
    rows = [
        {"period": "2026-01", "pdf_url": "a", "sha256": "same"},
        {"period": "2026-01", "pdf_url": "b", "sha256": "same"},
        {"period": "2026-02", "pdf_url": "c", "sha256": "one"},
        {"period": "2026-02", "pdf_url": "d", "sha256": "two"},
    ]
    state = adapter.duplicate_period_state(rows)
    assert state["2026-01"]["state"] == "SAME_PAYLOAD_MULTIPLE_MANIFESTATIONS"
    assert state["2026-02"]["state"] == "MULTIPLE_DISTINCT_PAYLOADS"


def test_replay_verifies_frozen_bytes_page_counts_units_and_no_identity_promotion(
    tmp_path, monkeypatch
):
    root = tmp_path
    raw = root / "raw" / "2026-01"
    raw.mkdir(parents=True)
    pdf = raw / "abc__report.pdf"
    pdf.write_bytes(b"%PDF-test-fixture")
    digest = adapter.sha256_file(pdf)

    manifest = [
        {
            "schema_version": adapter.SCHEMA_VERSION,
            "period": "2026-01",
            "manifestation_key": "m1",
            "source_state": "PASS",
            "raw_path": str(pdf.relative_to(root)),
            "sha256": digest,
            "byte_count": pdf.stat().st_size,
            "page_count": 1,
            "pdf_url": "https://example.test/report.pdf",
        }
    ]
    adapter.write_jsonl(root / "manifest.jsonl", manifest)
    page_text = "Hydro Net Generation 1 MWh"
    monkeypatch.setattr(adapter, "extract_pdf_pages", lambda _path: [page_text])
    render = root / "pages" / "2026-01" / digest / "page-0001.png"
    render.parent.mkdir(parents=True)
    render.write_bytes(b"render-fixture")
    adapter.write_jsonl(
        root / "page_index.jsonl",
        [
            {
                "manifestation_sha256": digest,
                "page_number": 1,
                "text_sha256": adapter.sha256_bytes(page_text.encode("utf-8")),
                "render_path": str(render.relative_to(root)),
                "render_sha256": adapter.sha256_file(render),
            }
        ],
    )
    adapter.write_jsonl(
        root / "normalized" / "observations.jsonl",
        [
            {
                "manifestation_sha256": digest,
                "page_number": 1,
                "normalized_unit": "MWH",
                "measurement_class": "ENERGY",
            },
            {
                "manifestation_sha256": digest,
                "page_number": 1,
                "normalized_unit": "MW",
                "measurement_class": "POWER",
            },
        ],
    )
    adapter.write_jsonl(
        root / "canonical" / "claims.jsonl",
        [
            {
                "manifestation_sha256": digest,
                "canonical_claim_state": "WITHHELD",
            }
        ],
    )

    replay = adapter.replay_snapshot(root)
    assert replay["overall"] == "PASS"
    assert replay["gates"] == {
        "SHA_REPLAY": "PASS",
        "PDF_SIGNATURE": "PASS",
        "PAGE_COUNT_CLOSURE": "PASS",
        "PAGE_TEXT_SHA_REPLAY": "PASS",
        "RENDER_SHA_REPLAY": "PASS",
        "NEGATIVE_AUTO_CERTIFICATION_DENY": "PASS",
        "TYPED_UNIT_VALIDATION": "PASS",
        "NO_NAME_ONLY_CANONICAL_PROMOTION": "PASS",
        "IDEMPOTENT_MANIFEST_KEYS": "PASS",
    }


def test_replay_fails_on_duplicate_manifestation_keys(tmp_path):
    adapter.write_jsonl(
        tmp_path / "manifest.jsonl",
        [
            {"period": "2026-01", "manifestation_key": "dup", "source_state": "SOURCE_UNAVAILABLE"},
            {"period": "2026-02", "manifestation_key": "dup", "source_state": "SOURCE_UNAVAILABLE"},
        ],
    )
    adapter.write_jsonl(tmp_path / "page_index.jsonl", [])
    adapter.write_jsonl(tmp_path / "normalized" / "observations.jsonl", [])
    adapter.write_jsonl(tmp_path / "canonical" / "claims.jsonl", [])
    replay = adapter.replay_snapshot(tmp_path)
    assert replay["gates"]["IDEMPOTENT_MANIFEST_KEYS"] == "FAIL"
    assert replay["overall"] == "FAIL"


def test_deterministic_archive_is_byte_identical_for_unchanged_inputs(tmp_path):
    adapter.write_jsonl(tmp_path / "manifest.jsonl", [{"manifestation_key": "x"}])
    adapter.write_jsonl(tmp_path / "page_index.jsonl", [])
    adapter.write_jsonl(tmp_path / "normalized" / "observations.jsonl", [])
    adapter.write_jsonl(tmp_path / "canonical" / "claims.jsonl", [])
    adapter.write_jsonl(tmp_path / "contradictions.jsonl", [])
    adapter.write_jsonl(tmp_path / "index_entries.jsonl", [])
    adapter.write_json(tmp_path / "denominator.json", {"gate": "PASS"})
    adapter.write_json(tmp_path / "replay.json", {"overall": "PASS"})

    first = adapter.deterministic_archive(tmp_path, tmp_path / "one.zip")
    second = adapter.deterministic_archive(tmp_path, tmp_path / "two.zip")
    assert first["sha256"] == second["sha256"]
    assert first["member_count"] == second["member_count"]


def test_canonical_candidates_remain_withheld():
    rows = [
        {
            "period": "2026-01",
            "manifestation_sha256": "a" * 64,
            "page_number": 2,
            "measurement_class": "ENERGY",
            "normalized_value": 123.4,
            "normalized_unit": "MWH",
            "raw_context": "Caonillas Net Generation 123.4 MWh",
        }
    ]
    candidates = adapter.build_canonical_candidates(rows)
    assert candidates[0]["identity_state"] == "CANDIDATE_NOT_IDENTITY"
    assert candidates[0]["canonical_claim_state"] == "WITHHELD"
    assert "name-only" in candidates[0]["reason"]


def test_landing_publication_date_prefers_explicit_metadata():
    html = """
    <html><head>
      <meta property="article:published_time" content="2026-04-30T10:30:00-04:00">
      <meta property="article:modified_time" content="2026-05-01T10:30:00-04:00">
    </head><body></body></html>
    """
    assert adapter.landing_publication_date(html) == "2026-04-30T10:30:00-04:00"


def test_negative_page_completeness_is_not_equivalent_to_certification():
    # The adapter intentionally exposes page-complete readiness separately.
    assert adapter.classify_hydro_text("Solar generation 42 MWh") == "HYDRO_ABSENT"
    # Certification eligibility is only written by acquisition and is always denied
    # automatically until independent visual semantic review occurs.
    fields = adapter.ManifestRow.__dataclass_fields__
    assert "negative_page_complete_ready" in fields
    assert "negative_certification_eligible" in fields
