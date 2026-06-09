"""End-to-end test for the canonical export pipeline.

Drives `scripts/federation_export.py` against the real `data/` corpus and
verifies BOTH halves of the canonical contract:
  - `exports/federation/*.jsonl + manifest.json`  (Hub-bound canonical streams)
  - `outputs/*.json`                              (operator-facing snapshot)

Skip-if guards against branches that lack the Z3 corpus (`data/aee_incidents.jsonl`
or `data/geo/`) so this test stays green on the parallel M-track lineage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from federation_export import (  # noqa: E402
    _compute_aggregates,
    _load_geo,
    _load_jsonl,
    build_outputs,
    build_streams,
    write_package,
)

NEEDS_Z3_CORPUS = pytest.mark.skipif(
    not (REPO_ROOT / "data/aee_incidents.jsonl").exists()
    or not (REPO_ROOT / "data/geo/pr_municipios.json").exists(),
    reason="Z3 corpus (aee_incidents.jsonl + data/geo/) absent on this branch",
)


@pytest.fixture(scope="module")
def real_corpus() -> dict:
    """Load the real merged corpus once per test module."""
    assets = _load_jsonl(REPO_ROOT / "data/utility_assets.jsonl")
    events = _load_jsonl(REPO_ROOT / "data/service_events.jsonl") + _load_jsonl(
        REPO_ROOT / "data/aee_incidents.jsonl"
    )
    geo = _load_geo(REPO_ROOT / "data/geo/pr_municipios.json")
    return {"assets": assets, "events": events, "geo": geo}


@NEEDS_Z3_CORPUS
def test_streams_round_trip_with_z3_corpus(real_corpus, tmp_path):
    """Streams (exports/federation/) write deterministically; Z3 wiring lands."""
    assets, events, geo = real_corpus["assets"], real_corpus["events"], real_corpus["geo"]
    now = "2026-06-08T13:45:24Z"
    streams = build_streams(assets, events, now, geo)

    # Z3 invariant: every aee_incident (T2 service_event with municipality) must
    # both materialize as an entity and carry a location block sourced from geo.
    service_events = [e for e in streams["entities"] if e["entity_type"] == "service_event"]
    with_muni = [e for e in service_events if e.get("location", {}).get("municipality")]
    assert len(with_muni) == 6, f"expected 6 AEE events with municipality, got {len(with_muni)}"
    for e in with_muni:
        loc = e["location"]
        assert "lat" in loc and "lon" in loc, f"AEE event missing lat/lon: {e['entity_id']}"

    # located_in relationships: one per asset-with-municipality + one per AEE event.
    located_in = [r for r in streams["relationships"] if r["relationship_type"] == "located_in"]
    assert len(located_in) >= 279, f"expected ≥279 located_in rels, got {len(located_in)}"

    # Write through write_package — manifest emerges schema-compliant.
    manifest_path = write_package(streams, tmp_path / "exports", "test", now)
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["producer"] == "aguayluz-pr"
    assert manifest["federation"]["hub_parent"] == "thehub-pr"
    assert {f["stream"] for f in manifest["files"]} == {"sources", "entities", "relationships"}


@NEEDS_Z3_CORPUS
def test_outputs_deliverable_against_real_corpus(real_corpus, tmp_path):
    """outputs/* — all 7 files materialize schema-valid against the real corpus."""
    assets, events = real_corpus["assets"], real_corpus["events"]
    aggregates = _compute_aggregates(assets, events)
    now = "2026-06-08T13:45:24Z"
    outputs = tmp_path / "outputs"

    counts = build_outputs(assets, events, aggregates, now, outputs)

    # All 7 declared deliverables present.
    expected_files = {
        "utility_assets.json", "service_events.json", "source_manifest.json",
        "review_queue.json", "bridge_summary.json", "base44_export.json",
        "integration_report.json",
    }
    assert {p.name for p in outputs.iterdir()} == expected_files

    # Aggregates spot-checks — these numbers come straight from the merged
    # corpus (273+ assets ranging across power/water/USGS, 2 PREPS + 6 AEE
    # events). 240 needs_review = 234 OSM water + 6 AEE; 0 blocked.
    assert counts["service_events"] == len(events)
    assert counts["review_queue_items"] == aggregates["records_review"]
    assert aggregates["records_review"] >= 240, (
        f"expected ≥240 needs_review records (234 OSM water + 6 AEE), "
        f"got {aggregates['records_review']}"
    )
    assert aggregates["records_blocked"] == 0
    assert len(aggregates["municipalities_covered"]) >= 25

    # Review queue: every needs_review/blocked record makes it; nothing extra.
    queue = json.loads((outputs / "review_queue.json").read_text())
    assert queue["module_id"] == "aguayluz-pr"
    assert len(queue["items"]) == aggregates["records_review"] + aggregates["records_blocked"]
    severities = {item["severity"] for item in queue["items"]}
    assert severities <= {"warn", "block", "info"}
    # Every record_ref must correspond to an actual asset_id or event_id in the
    # input corpus — guards against future ID-mapping bugs.
    known_ids = {r.get("asset_id") for r in assets} | {r.get("event_id") for r in events}
    queue_refs = {item["record_ref"] for item in queue["items"]}
    unknown = queue_refs - known_ids
    assert not unknown, f"review_queue refs not found in corpus: {sorted(unknown)[:5]}"

    # Base44 envelope: PASS status, coverage 100%, paths point to siblings.
    base44 = json.loads((outputs / "base44_export.json").read_text())
    assert base44["module_id"] == "aguayluz-pr"
    assert base44["status"] == "PASS"
    assert base44["coverage_pct"] == 100.0
    assert base44["records_total"] == aggregates["records_total"]
    assert base44["records_review"] == aggregates["records_review"]
    assert base44["source_manifest_path"] == "outputs/source_manifest.json"
    assert base44["integration_report_path"] == "outputs/integration_report.json"

    # Bridge summary: municipalities_covered is sorted+dedup and review_status
    # reflects the presence of needs_review records.
    bridge = json.loads((outputs / "bridge_summary.json").read_text())
    assert bridge["municipalities_covered"] == sorted(set(bridge["municipalities_covered"]))
    assert bridge["review_status"] == "needs_review"
    assert "thehub-pr" in bridge["linked_modules"]

    # Integration report: gate ledger covers all 8 gates, every status valid.
    report = json.loads((outputs / "integration_report.json").read_text())
    assert {g["id"] for g in report["gates"]} == {
        f"G0{i}_" + name for i, name in enumerate(
            ["SCHEMA", "SOURCE_MANIFEST", "CONFIDENCE", "REVIEW_QUEUE",
             "COVERAGE_LEDGER", "BASE44_EXPORT", "NO_SECRETS", "TESTS"], start=1)
    }
    assert all(g["status"] in {"PASS", "WARN", "FAIL", "SKIP"} for g in report["gates"])
    assert report["coverage"]["coverage_pct"] == 100.0


@NEEDS_Z3_CORPUS
def test_aggregates_are_pure(real_corpus):
    """_compute_aggregates is a pure function — same input → same output."""
    a, b = real_corpus["assets"], real_corpus["events"]
    one = _compute_aggregates(a, b)
    two = _compute_aggregates(a, b)
    assert one == two
    # And the input lists are untouched.
    assert len(a) == len(real_corpus["assets"])
    assert len(b) == len(real_corpus["events"])
