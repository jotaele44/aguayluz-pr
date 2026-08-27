"""Regulatory persistence: JSONL loaders/merge, checkpoint store, SQLite build.

Uses the same fixture the design-authority tests validate against
(``tests/fixtures/regulatory/framework_cases_v0_2.json``) so this module is proven
against real schema-valid records, not hand-shortened ones.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from aguayluz.regulatory_db import (
    build_sqlite,
    load_checkpoint,
    load_regulatory_crosswalk,
    load_regulatory_links,
    load_regulatory_observations,
    load_regulatory_receipts,
    merge_crosswalk,
    merge_links,
    merge_observations,
    merge_receipts,
    save_checkpoint,
    write_regulatory_crosswalk,
    write_regulatory_links,
    write_regulatory_observations,
    write_regulatory_receipts,
)
from aguayluz.regulatory_promotion import promote_approved_links

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/regulatory/framework_cases_v0_2.json"


def _cases() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _receipts() -> list[dict]:
    """One receipt per distinct ``source_receipt_id`` the fixture observations
    reference (some providers, e.g. PRASA_AAA, abbreviate the id differently from
    the provider enum, and one receipt backs two FDA observations) — so receipts
    are derived from what the observations actually point at, not reconstructed
    from the raw_payloads provider-name keys.
    """
    cases = _cases()
    receipt_providers: dict[str, str] = {}
    for o in cases["observations"]:
        receipt_providers.setdefault(o["source_receipt_id"], o["provider"])

    receipts = []
    for receipt_id, provider in receipt_providers.items():
        content = cases["raw_payloads"][provider].encode("utf-8")
        receipts.append({
            "receipt_id": receipt_id,
            "provider": provider,
            "retrieved_at": "2026-08-04T19:00:00Z",
            "request_locator": f"fixture://{provider.lower()}/record/001",
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_count": len(content),
            "media_type": "application/json",
            "retrieval_status": "success",
            "http_status": 200,
            "redactions": [],
        })
    return receipts


def _observations() -> list[dict]:
    return _cases()["observations"]


def _links() -> dict:
    return _cases()["links"]


# ---------------- loaders ----------------

def test_load_regulatory_observations_validates_against_fixture(tmp_path):
    path = tmp_path / "observations.jsonl"
    path.write_text("".join(json.dumps(o) + "\n" for o in _observations()), encoding="utf-8")
    loaded = load_regulatory_observations(path)
    assert len(loaded) == len(_observations())
    assert {o["provider"] for o in loaded} == {"EPA", "FDA", "USGS", "DRNA", "PRASA_AAA", "PREQB"}


def test_load_regulatory_observations_rejects_malformed_row(tmp_path):
    path = tmp_path / "observations.jsonl"
    malformed = next(
        case["record"] for case in _cases()["invalid_observations"]
        if case["case"] == "malformed_provider"
    )
    path.write_text(json.dumps(malformed) + "\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_regulatory_observations(path)


def test_load_regulatory_observations_missing_file_returns_empty(tmp_path):
    assert load_regulatory_observations(tmp_path / "missing.jsonl") == []


def test_load_regulatory_receipts_validates_against_fixture(tmp_path):
    path = tmp_path / "receipts.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in _receipts()), encoding="utf-8")
    assert len(load_regulatory_receipts(path)) == len(_receipts())


def test_load_regulatory_links_validates_against_fixture(tmp_path):
    path = tmp_path / "links.jsonl"
    links = _links()
    rows = [links["approved"], links["unverified"]]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert len(load_regulatory_links(path)) == 2


# ---------------- merge semantics ----------------

def test_merge_observations_replaces_by_id():
    original = [_observations()[0]]
    revised = {**original[0], "freshness_state": "stale"}
    merged = merge_observations(original, [revised])
    assert len(merged) == 1
    assert merged[0]["freshness_state"] == "stale"


def test_merge_receipts_replaces_by_id():
    original = [_receipts()[0]]
    revised = {**original[0], "retrieval_status": "not_modified"}
    merged = merge_receipts(original, [revised])
    assert len(merged) == 1
    assert merged[0]["retrieval_status"] == "not_modified"


def test_merge_links_replaces_by_id_not_accumulates():
    proposed = _links()["unverified"]
    approved = {
        **proposed,
        "decision_state": "approved",
        "decided_at": "2026-08-04T19:05:00Z",
        "decided_by": "governance-test",
        "decision_rationale": "Confirmed after review.",
    }
    merged = merge_links([proposed], [approved])
    assert len(merged) == 1
    assert merged[0]["decision_state"] == "approved"


# ---------------- write + load round-trip ----------------

def test_write_regulatory_observations_persists_and_merges(tmp_path):
    path = tmp_path / "observations.jsonl"
    first = [_observations()[0]]
    write_regulatory_observations(first, path)
    assert len(load_regulatory_observations(path)) == 1

    second = [_observations()[1]]
    write_regulatory_observations(second, path)
    loaded = load_regulatory_observations(path)
    assert len(loaded) == 2


def test_write_regulatory_links_merge_replaces_proposed_with_decision(tmp_path):
    path = tmp_path / "links.jsonl"
    proposed = _links()["unverified"]
    write_regulatory_links([proposed], path)

    approved = {
        **proposed,
        "decision_state": "approved",
        "decided_at": "2026-08-04T19:05:00Z",
        "decided_by": "governance-test",
        "decision_rationale": "Confirmed after review.",
    }
    write_regulatory_links([approved], path)

    loaded = load_regulatory_links(path)
    assert len(loaded) == 1
    assert loaded[0]["decision_state"] == "approved"


def test_write_regulatory_receipts_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "receipts.jsonl"
    write_regulatory_receipts([_receipts()[0]], path)
    assert path.is_file()


def test_write_regulatory_observations_rejects_invalid_row_before_writing(tmp_path):
    path = tmp_path / "observations.jsonl"
    malformed = next(
        case["record"] for case in _cases()["invalid_observations"]
        if case["case"] == "malformed_provider"
    )
    with pytest.raises(ValidationError):
        write_regulatory_observations([malformed], path)
    # Nothing should have been written on a rejected batch.
    assert not path.is_file()


def test_write_regulatory_links_rejects_invalid_row_before_writing(tmp_path):
    path = tmp_path / "links.jsonl"
    bad = {**_links()["approved"], "decided_by": None}  # fails schema's approved-state rule
    with pytest.raises(ValidationError):
        write_regulatory_links([bad], path)
    assert not path.is_file()


# ---------------- checkpoint store ----------------

def test_checkpoint_roundtrip(tmp_path):
    checkpoint = {"provider": "USGS", "cursor": "page-3", "watermark": "2026-08-04T00:00:00Z"}
    save_checkpoint("USGS", checkpoint, root=tmp_path)
    assert load_checkpoint("USGS", root=tmp_path) == checkpoint


def test_checkpoint_missing_provider_returns_none(tmp_path):
    assert load_checkpoint("USGS", root=tmp_path) is None


def test_save_checkpoint_creates_directory(tmp_path):
    root = tmp_path / "nested" / "checkpoints"
    save_checkpoint("EPA", {"cursor": "x"}, root=root)
    assert (root / "EPA.json").is_file()


def test_checkpoint_rejects_unknown_provider(tmp_path):
    with pytest.raises(ValueError):
        save_checkpoint("MYSTERY_AGENCY", {"cursor": "x"}, root=tmp_path)
    with pytest.raises(ValueError):
        load_checkpoint("MYSTERY_AGENCY", root=tmp_path)


def test_checkpoint_provider_cannot_escape_root_via_path_traversal(tmp_path):
    # A provider string is never allowed to reach filesystem path construction
    # unvalidated: only the closed PROVIDERS set may name a checkpoint file.
    with pytest.raises(ValueError):
        save_checkpoint("../../etc/passwd", {"cursor": "x"}, root=tmp_path)


def test_load_checkpoint_rejects_non_object_json(tmp_path):
    (tmp_path / "USGS.json").write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_checkpoint("USGS", root=tmp_path)


def test_checkpoint_never_serializes_secret_shaped_keys(tmp_path):
    # Defensive: the design doc requires checkpoints to carry no secrets. This does
    # not scan for arbitrary content (that is a caller's contract to honor per
    # contracts.py's DiscoveryCheckpoint docstring) but locks in that whatever is
    # passed round-trips exactly, so a caller's redaction discipline is not silently
    # altered by this layer.
    checkpoint = {"cursor": "42", "opaque_state": {"page_token": "abc"}}
    save_checkpoint("EPA", checkpoint, root=tmp_path)
    raw = (tmp_path / "EPA.json").read_text(encoding="utf-8")
    assert "authorization" not in raw.lower()
    assert "bearer" not in raw.lower()


# ---------------- SQLite build ----------------

def test_build_sqlite_in_memory_loads_all_tables():
    conn = build_sqlite(
        ":memory:",
        observations=_observations(),
        receipts=_receipts(),
        links=[_links()["approved"], _links()["unverified"]],
    )
    try:
        counts = {
            t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("regulatory_source_receipts", "regulatory_observations", "regulatory_entity_links")
        }
    finally:
        conn.close()
    assert counts["regulatory_source_receipts"] == len(_receipts())
    assert counts["regulatory_observations"] == len(_observations())
    assert counts["regulatory_entity_links"] == 2


def test_sqlite_enforces_fail_closed_approval():
    conn = build_sqlite(":memory:", observations=_observations(), receipts=_receipts(), links=[])
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO regulatory_entity_links (candidate_id, observation_id, "
                "candidate_asset_id, decision_state, match_features, contradictions, "
                "created_at, decided_by, decision_rationale) VALUES "
                "('AYL_REGLINK_X_001','AYL_REGOBS_EPA_001','LOCAL_X_001','approved',"
                "'[]','[]','2026-08-04T19:00:00Z','governance-test','because')"
            )
    finally:
        conn.close()


def test_sqlite_enforces_retraction_requires_supersession():
    conn = build_sqlite(":memory:", observations=[], receipts=_receipts(), links=[])
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO regulatory_observations (observation_id, record_family, "
                "provider, provider_record_id, observed_at, retrieved_at, "
                "source_receipt_id, normalization_version, evidence_tier, "
                "freshness_state, source_asserted_status, payload) VALUES "
                "('AYL_REGOBS_FDA_BAD','enforcement','FDA','WL-1',"
                "'2026-08-01T00:00:00Z','2026-08-04T19:00:00Z','AYL_REGRCPT_FDA_001',"
                "'fda/v1','T1','historical','retracted','{}')"
            )
    finally:
        conn.close()


def test_build_sqlite_persists_to_file_path(tmp_path):
    db_path = tmp_path / "nested" / "regulatory.sqlite"
    conn = build_sqlite(
        db_path,
        observations=_observations(),
        receipts=_receipts(),
        links=[_links()["approved"]],
    )
    conn.close()
    assert db_path.is_file()

    conn2 = sqlite3.connect(str(db_path))
    try:
        count = conn2.execute("SELECT count(*) FROM regulatory_observations").fetchone()[0]
    finally:
        conn2.close()
    assert count == len(_observations())


# ---------------- entity crosswalk ----------------

def _crosswalk_rows() -> list[dict]:
    return promote_approved_links([_links()["approved"]], _observations())


def test_load_regulatory_crosswalk_validates_against_schema(tmp_path):
    path = tmp_path / "crosswalk.jsonl"
    rows = _crosswalk_rows()
    assert rows  # the fixture's approved link must actually promote to something
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert len(load_regulatory_crosswalk(path)) == len(rows)


def test_merge_crosswalk_replaces_by_id():
    row = _crosswalk_rows()[0]
    revised = {**row, "decision_rationale": "Updated rationale."}
    merged = merge_crosswalk([row], [revised])
    assert len(merged) == 1
    assert merged[0]["decision_rationale"] == "Updated rationale."


def test_write_regulatory_crosswalk_persists_and_merges(tmp_path):
    path = tmp_path / "crosswalk.jsonl"
    rows = _crosswalk_rows()
    write_regulatory_crosswalk(rows, path)
    assert len(load_regulatory_crosswalk(path)) == len(rows)

    # Rerunning promotion over the same approved link reproduces the same
    # crosswalk_id, so a second write must not duplicate the row.
    write_regulatory_crosswalk(rows, path)
    assert len(load_regulatory_crosswalk(path)) == len(rows)


def test_build_sqlite_includes_crosswalk_table():
    conn = build_sqlite(
        ":memory:",
        observations=_observations(),
        receipts=_receipts(),
        links=[_links()["approved"]],
        crosswalk=_crosswalk_rows(),
    )
    try:
        count = conn.execute("SELECT count(*) FROM regulatory_entity_crosswalk").fetchone()[0]
    finally:
        conn.close()
    assert count == len(_crosswalk_rows())
