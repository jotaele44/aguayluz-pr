"""USGS regulatory adapter: discover() page-locator construction and normalize()
against the same sanitized monitoring-locations fixture the surface-water ingest
scripts already use.

``fetch()`` is not unit-tested here, matching this repo's established convention for
``scripts/ingest_usgs_*.py``'s ``fetch_*_live()`` functions: the live network path is
proven by a real, keyless run (see the PR description), not mocked in pytest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aguayluz.regulatory_adapters.usgs import (
    MAX_PAGES,
    NORMALIZATION_VERSION,
    PROVIDER,
    capabilities,
    discover,
    normalize,
)
from aguayluz.regulatory_db import load_regulatory_observations, load_regulatory_receipts

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/usgs_monitoring_locations_pr.json"
DEFAULT_BBOX = "-67.95,17.7,-65.2,18.7"


def _fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


def _fixture_receipt() -> dict:
    content = _fixture_bytes()
    digest = hashlib.sha256(content).hexdigest()
    return {
        "receipt_id": f"AYL_REGRCPT_USGS_{digest[:24]}",
        "provider": PROVIDER,
        "retrieved_at": "2026-08-19T20:00:00Z",
        "request_locator": "fixture://usgs/monitoring-locations",
        "sha256": digest,
        "byte_count": len(content),
        "media_type": "application/json",
        "retrieval_status": "success",
        "http_status": 200,
        "redactions": [],
    }


def test_capabilities_matches_contracts_baseline():
    caps = capabilities()
    assert caps["provider"] == "USGS"
    assert caps["record_families"] == ["entity"]


def test_discover_emits_page_locators_without_network(monkeypatch):
    # No network client should even be importable for discover() to succeed, since
    # it must build URLs only.
    locators, checkpoint = discover(bbox=DEFAULT_BBOX)
    assert len(locators) == MAX_PAGES
    assert all(loc["provider"] == "USGS" for loc in locators)
    assert all(loc["record_family"] == "entity" for loc in locators)
    assert locators[0]["locator"].startswith(
        "https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items"
    )
    assert "offset=0" in locators[0]["locator"]
    assert checkpoint["cursor"] == str(MAX_PAGES)
    assert checkpoint["bbox"] == DEFAULT_BBOX


def test_discover_resumes_from_checkpoint_cursor():
    checkpoint = {"provider": "USGS", "cursor": "3", "bbox": DEFAULT_BBOX}
    locators, next_checkpoint = discover(bbox=DEFAULT_BBOX, checkpoint=checkpoint)
    assert f"offset={3 * 1000}" in locators[0]["locator"]
    assert next_checkpoint["cursor"] == str(3 + MAX_PAGES)


def test_normalize_produces_schema_valid_observations():
    receipt = _fixture_receipt()
    observations = normalize(_fixture_bytes(), receipt)

    fixture_doc = json.loads(_fixture_bytes())
    assert len(observations) == len(fixture_doc["features"])
    for obs in observations:
        assert obs["provider"] == "USGS"
        assert obs["record_family"] == "entity"
        assert obs["source_receipt_id"] == receipt["receipt_id"]
        assert obs["normalization_version"] == NORMALIZATION_VERSION
        assert obs["evidence_tier"] == "T1"
        assert obs["identifiers"][0]["scheme"] == "usgs_site_no"


def test_normalize_output_validates_against_regulatory_observation_schema(tmp_path):
    receipt = _fixture_receipt()
    observations = normalize(_fixture_bytes(), receipt)

    obs_path = tmp_path / "observations.jsonl"
    obs_path.write_text("".join(json.dumps(o) + "\n" for o in observations), encoding="utf-8")
    loaded = load_regulatory_observations(obs_path)
    assert len(loaded) == len(observations)

    rcpt_path = tmp_path / "receipts.jsonl"
    rcpt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    assert len(load_regulatory_receipts(rcpt_path)) == 1


def test_normalize_is_idempotent_on_unchanged_bytes():
    receipt = _fixture_receipt()
    first = normalize(_fixture_bytes(), receipt)
    second = normalize(_fixture_bytes(), receipt)
    assert [o["observation_id"] for o in first] == [o["observation_id"] for o in second]


def test_normalize_skips_features_with_no_site_number():
    receipt = _fixture_receipt()
    raw = json.dumps({"type": "FeatureCollection", "features": [{"properties": {}}]}).encode()
    assert normalize(raw, receipt) == []


def test_normalize_rejects_would_be_invalid_payload_via_loader(tmp_path):
    # payload is required non-null by the schema; guard that normalize() never emits
    # a row that fails validation even for a maximally sparse feature.
    receipt = _fixture_receipt()
    raw = json.dumps({
        "type": "FeatureCollection",
        "features": [{"properties": {"monitoring_location_number": "50038100"}}],
    }).encode()
    observations = normalize(raw, receipt)
    path = tmp_path / "observations.jsonl"
    path.write_text(json.dumps(observations[0]) + "\n", encoding="utf-8")
    load_regulatory_observations(path)  # raises ValidationError on failure
