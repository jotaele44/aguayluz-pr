"""scripts/ingest_prdner_well_bands.py end to end, offline.

Positive inputs are real captures: the USGS page (SHA-256 20d8814f...) and the five
``USGSGW_`` asset rows copied verbatim from data/utility_assets.jsonl. Cases that need a
shape the source did not happen to publish (a moved band edge, a landing page, a missing
asset) are CONSTRUCTED from those captures and say so.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from aguayluz import aquifer_bands as ab

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
PAGE = FIXTURES / "prdner_hydro_conditions_selected_wells.html"
ASSETS = FIXTURES / "prdner_usgsgw_assets.jsonl"
SCHEMAS = REPO / "schemas" / "aquifer-bands" / "v1"
NOW = "2026-11-08T16:00:00Z"
LATER = "2026-11-15T16:00:00Z"

_SPEC = importlib.util.spec_from_file_location(
    "ingest_prdner_well_bands", REPO / "scripts" / "ingest_prdner_well_bands.py"
)
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest
_SPEC.loader.exec_module(ingest)


def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def run(data_dir, *extra, src=PAGE, now=NOW, assets=ASSETS):
    return ingest.main(["--src", str(src), "--data-dir", str(data_dir), "--assets", str(assets),
                        "--now", now, *extra])


def registry(data_dir):
    return ab.read_jsonl(Path(data_dir) / ab.REGISTRY_FILE)


def receipt(data_dir):
    return json.loads((Path(data_dir) / ab.RECEIPT_FILE).read_text())


def mutated_page(tmp_path, old: str, new: str) -> Path:
    text = PAGE.read_bytes().decode("latin-1")
    assert old in text, f"fixture no longer contains {old!r}"
    target = tmp_path / "mutated.html"
    target.write_bytes(text.replace(old, new).encode("latin-1"))
    return target


# ── a clean run ───────────────────────────────────────────────────────────────
def test_offline_run_closes_arithmetic_binds_and_freezes_the_bytes(tmp_path):
    assert run(tmp_path) == 0
    rc = receipt(tmp_path)
    digest = hashlib.sha256(PAGE.read_bytes()).hexdigest()
    assert rc["last_status"] == "PASS" and rc["last_error"] is None
    assert rc["last_success"]["byte_sha256"] == digest
    assert rc["last_success"]["arithmetic"] == {
        "source": 5, "retained": 5, "excluded": 0, "unresolved": 0,
        "accounted": 5, "delta": 0, "state": "PASS",
    }
    assert rc["last_success"]["revisions_appended"] == 5
    assert set(rc["last_success"]["ladder_discrepancies"]) == {"175947066130601", "175910066155500"}

    rows = registry(tmp_path)
    assert [r["asset_id"] for r in rows] == [
        "USGSGW_175934066364800", "USGSGW_180057066311300", "USGSGW_175734066233300",
        "USGSGW_175947066130601", "USGSGW_175910066155500",
    ]
    assert all(r["revision"] == 1 and r["supersedes"] is None for r in rows)
    assert all(r["effective_date"] is None and r["evidence_tier"] == "T2" for r in rows)
    assert all(r["source_byte_sha256"] == digest for r in rows)
    assert {r["municipality"] for r in rows} == {"Ponce", "Juana Díaz", "Santa Isabel", "Salinas"}
    # The exact bytes the source sent are kept, hash-addressed, before anything is parsed.
    assert (tmp_path / ab.SNAPSHOT_DIRNAME / f"{digest}.html").read_bytes() == PAGE.read_bytes()


def test_rows_and_receipt_validate_against_their_schemas(tmp_path):
    assert run(tmp_path) == 0
    row_schema, receipt_schema = validator("aquifer_band_registry.schema.json"), validator("aquifer_band_receipt.schema.json")
    for row in registry(tmp_path):
        row_schema.validate(row)
    receipt_schema.validate(receipt(tmp_path))


def test_registry_schema_rejects_a_fabricated_effective_date_and_stray_keys(tmp_path):
    assert run(tmp_path) == 0
    row_schema = validator("aquifer_band_registry.schema.json")
    good = registry(tmp_path)[0]
    for bad in (
        {**good, "effective_date": "2026-01-01"},      # the source publishes none; never invent one
        {**good, "evidence_tier": "T1"},               # operational documentation, not a primary record
        {**good, "parameter_code": "62610"},           # opposite direction
        {**good, "asset_id": "USGS_175934066364800"},  # wells are USGSGW_
        {**good, "note": "extra"},
        {**good, "bands": good["bands"][:4]},
    ):
        assert not row_schema.is_valid(bad), bad


# ── idempotence and history ───────────────────────────────────────────────────
def test_rerun_with_the_same_clock_leaves_the_registry_byte_identical(tmp_path):
    assert run(tmp_path) == 0
    registry_bytes = (tmp_path / ab.REGISTRY_FILE).read_bytes()
    first = receipt(tmp_path)
    assert first["last_success"]["revisions_appended"] == 5
    assert run(tmp_path) == 0
    assert (tmp_path / ab.REGISTRY_FILE).read_bytes() == registry_bytes
    # The receipt reports what THIS run did (nothing new to append); everything else is unchanged.
    second = receipt(tmp_path)
    assert second["last_success"]["revisions_appended"] == 0
    first["last_success"]["revisions_appended"] = 0
    assert second == first


def test_rerun_later_appends_nothing_and_moves_only_the_receipt_clock(tmp_path):
    assert run(tmp_path) == 0
    registry_before = (tmp_path / ab.REGISTRY_FILE).read_bytes()
    assert run(tmp_path, now=LATER) == 0
    assert (tmp_path / ab.REGISTRY_FILE).read_bytes() == registry_before
    rc = receipt(tmp_path)
    assert rc["last_attempt_utc"] == LATER and rc["last_success_utc"] == LATER
    assert rc["last_success"]["revisions_appended"] == 0


def test_a_moved_edge_appends_one_superseding_revision_and_never_rewrites_history(tmp_path):
    """CONSTRUCTED: Aguirre HW 5B's Critical onset moved from 23.43 to 23.40 ft."""
    assert run(tmp_path) == 0
    before = (tmp_path / ab.REGISTRY_FILE).read_text()
    moved = mutated_page(tmp_path, "23.43", "23.40")
    assert run(tmp_path, src=moved, now=LATER) == 0

    after = (tmp_path / ab.REGISTRY_FILE).read_text()
    assert after.startswith(before), "earlier revisions must stay byte-for-byte"
    rows = registry(tmp_path)
    assert len(rows) == 6
    new = rows[-1]
    assert (new["site_no"], new["revision"], new["supersedes"]) == (
        "175947066130601", 2, "AQBAND:175947066130601:r1")
    assert new["first_observed_utc"] == LATER
    assert ab.critical_onset_ft(ab.bands_from_json(new["bands"])) == 23.40
    assert receipt(tmp_path)["last_success"]["revisions_appended"] == 1
    current = ab.current_registry(rows)
    assert current["175947066130601"]["revision"] == 2
    assert all(current[s]["revision"] == 1 for s in current if s != "175947066130601")


# ── fail closed ───────────────────────────────────────────────────────────────
def test_unreadable_source_writes_a_fail_receipt_and_keeps_the_last_success(tmp_path):
    assert run(tmp_path) == 0
    registry_before = (tmp_path / ab.REGISTRY_FILE).read_bytes()
    success_before = receipt(tmp_path)["last_success"]
    assert run(tmp_path, src=tmp_path / "nope.html", now=LATER) == 1
    rc = receipt(tmp_path)
    assert rc["last_status"] == "FAIL" and "could not acquire" in rc["last_error"]
    assert rc["last_attempt_utc"] == LATER and rc["last_success_utc"] == NOW
    assert rc["last_success"] == success_before
    assert (tmp_path / ab.REGISTRY_FILE).read_bytes() == registry_before
    validator("aquifer_band_receipt.schema.json").validate(rc)


def test_a_page_that_no_longer_parses_fails_closed_but_the_bytes_are_kept(tmp_path):
    """CONSTRUCTED: the landing page the extensionless URL redirects to."""
    landing = tmp_path / "landing.html"
    landing.write_bytes(b"<html><body><h1>Caribbean-Florida Water Science Center</h1></body></html>")
    assert run(tmp_path, src=landing) == 1
    digest = hashlib.sha256(landing.read_bytes()).hexdigest()
    assert (tmp_path / ab.SNAPSHOT_DIRNAME / f"{digest}.html").is_file()
    assert not (tmp_path / ab.REGISTRY_FILE).exists()
    rc = receipt(tmp_path)
    assert rc["last_status"] == "FAIL" and rc["last_success"] is None
    assert digest[:12] in rc["last_error"]


def test_a_failed_run_after_a_good_one_leaves_the_registry_untouched(tmp_path):
    assert run(tmp_path) == 0
    before = (tmp_path / ab.REGISTRY_FILE).read_bytes()
    drifted = mutated_page(tmp_path, "Optimum condition", "Optimal condition")
    assert run(tmp_path, src=drifted, now=LATER) == 1
    assert (tmp_path / ab.REGISTRY_FILE).read_bytes() == before
    assert receipt(tmp_path)["last_success_utc"] == NOW


def test_dry_run_writes_nothing(tmp_path, capsys):
    assert run(tmp_path, "--dry-run") == 0
    assert list(tmp_path.iterdir()) == []
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["revisions_appended"] == 5


def test_dry_run_failure_also_writes_nothing(tmp_path):
    assert run(tmp_path, "--dry-run", src=tmp_path / "nope.html") == 1
    assert list(tmp_path.iterdir()) == []


def test_a_well_with_no_asset_fails_the_run_instead_of_covering_four_of_five(tmp_path):
    """CONSTRUCTED: the Aguirre HW 5B asset row removed."""
    partial = tmp_path / "assets.jsonl"
    partial.write_text("".join(
        line for line in ASSETS.read_text().splitlines(keepends=True) if "175947066130601" not in line))
    data = tmp_path / "data"
    assert run(data, assets=partial) == 1
    assert not (data / ab.REGISTRY_FILE).exists()
    assert "175947066130601: no USGSGW_175947066130601 asset" in receipt(data)["last_error"]


def test_a_title_that_does_not_corroborate_the_asset_fails(tmp_path):
    """CONSTRUCTED: the asset id is right but its name is a different well."""
    renamed = tmp_path / "assets.jsonl"
    renamed.write_text(ASSETS.read_text().replace("Piezometer Rasa D, Salinas, Pr", "Piezometer Other, Salinas, Pr"))
    data = tmp_path / "data"
    assert run(data, assets=renamed) == 1
    assert "does not corroborate" in receipt(data)["last_error"]
    assert not (data / ab.REGISTRY_FILE).exists()


def test_bad_clock_override_is_rejected(tmp_path, capsys):
    assert run(tmp_path, now="not-a-time") == 2
    assert "ISO 8601" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_live_path_goes_through_fetch_page(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "fetch_page", lambda *a, **k: PAGE.read_bytes())
    code = ingest.main(["--data-dir", str(tmp_path), "--assets", str(ASSETS), "--now", NOW])
    assert code == 0 and len(registry(tmp_path)) == 5


# ── acquisition: only a plain 200 HTML document is accepted ──────────────────
httpx = pytest.importorskip("httpx")


# Captured once: a second _serve() in one test must wrap the real class, not the first patch.
_REAL_CLIENT = httpx.Client


def _serve(monkeypatch, handler):
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)
    )


def test_a_redirect_is_refused_not_followed(monkeypatch):
    """The extensionless URL 301s to a generic landing page. Following it would freeze that."""
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(301, headers={"location": "https://www.usgs.gov/centers/car-fl-water"})

    _serve(monkeypatch, handler)
    with pytest.raises(ingest.AcquisitionError, match="redirected .*refusing to follow"):
        ingest.fetch_page("https://pr.water.usgs.gov/drought/hydro_conditions_selected_wells")
    assert seen == ["https://pr.water.usgs.gov/drought/hydro_conditions_selected_wells"]


def test_a_non_200_or_non_html_response_is_refused(monkeypatch):
    _serve(monkeypatch, lambda request: httpx.Response(404, text="gone"))
    with pytest.raises(ingest.AcquisitionError, match="HTTP 404"):
        ingest.fetch_page()
    _serve(monkeypatch, lambda request: httpx.Response(200, text="{}", headers={"content-type": "application/json"}))
    with pytest.raises(ingest.AcquisitionError, match="content-type"):
        ingest.fetch_page()


def test_a_plain_200_html_page_is_returned_byte_for_byte(monkeypatch):
    body = PAGE.read_bytes()
    _serve(monkeypatch, lambda request: httpx.Response(200, content=body, headers={"content-type": "text/html"}))
    assert ingest.fetch_page() == body


def test_the_documented_page_url_is_the_html_form():
    assert ab.PAGE_URL.endswith("hydro_conditions_selected_wells.html")
