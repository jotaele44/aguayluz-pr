"""Synthetic EIA failures, crash replay, independent counters and lease fencing."""

import hashlib
import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx
import jsonschema
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aguayluz.electricity.eia import EIAClient
from aguayluz.electricity.jobs import AcquisitionJobs, JobConflict, MonthlyJobRequest
from aguayluz.electricity.projection import electricity_projection
from aguayluz.electricity.store import EvidenceStore


def spec(**updates):
    return MonthlyJobRequest(
        **(
            dict(
                request_id=uuid4().hex,
                endpoint="facility-fuel",
                data_column="generation",
                state_facet="state",
                start="2026-01",
                end="2026-03",
                page_size=1,
            )
            | updates
        )
    )


def fixture_api(store, monkeypatch, modify=lambda request, response: response):
    monkeypatch.setenv("EIA_API_KEY", "synthetic-job-credential")

    def respond(request):
        if request.url.path.endswith("/data/"):
            offset = int(request.url.params["offset"])
            response = {
                "total": "3",
                "data": [{"state": "PR", "period": f"2026-0{offset + 1}", "generation": offset}],
            }
        elif "/facet/" in request.url.path:
            response = {"facets": [{"id": "PR"}], "totalFacets": "1"}
        else:
            response = {
                "facets": [{"id": "state"}],
                "frequency": [{"id": "monthly"}],
                "data": {"generation": {}},
            }
        changed = modify(request, response)
        return (
            changed
            if isinstance(changed, httpx.Response)
            else httpx.Response(200, json={"response": changed})
        )

    return EIAClient(
        store, client=httpx.Client(transport=httpx.MockTransport(respond)), sleep=lambda _: None
    )


def advance(jobs, job, api, count=1):
    for _ in range(count):
        job = jobs.step(job["job_id"], job["version"], client=api)
    return job


def test_read_only_empty_and_idempotent_creation(tmp_path):
    store = EvidenceStore(tmp_path / "absent")
    jobs = AcquisitionJobs(store)
    assert jobs.list() == {"jobs": [], "total": 0, "next_offset": None}
    assert not store.root.exists()
    s = spec()
    first = jobs.create(s)
    assert jobs.create(s) == first
    with pytest.raises(JobConflict, match="REQUEST_CONFLICT"):
        jobs.create(s.model_copy(update={"end": "2026-04"}))
    assert "lease_token" not in first


def test_runtime_credential_cannot_enter_job_spec(tmp_path, monkeypatch):
    monkeypatch.setenv("EIA_API_KEY", "syntheticCredentialValue")
    jobs = AcquisitionJobs(EvidenceStore(tmp_path / "absent"))
    with pytest.raises(ValueError, match="credential values refused"):
        jobs.create(spec(data_column="syntheticCredentialValue"))
    assert not jobs.store.root.exists()


def test_missing_credential_is_failed_not_zero_and_does_not_send_a_request(tmp_path, monkeypatch):
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    store = EvidenceStore(tmp_path)
    jobs = AcquisitionJobs(store)

    def never(_):
        pytest.fail("no credential must mean no transport request")

    api = EIAClient(store, client=httpx.Client(transport=httpx.MockTransport(never)))
    result = advance(jobs, jobs.create(spec()), api)
    assert result["status"] == "FAILED" and result["error"] == "EIA_CREDENTIAL_MISSING"
    assert result["total"] is None and result["receipt_sha256"] == []


def test_partial_page_overlap_is_not_counted_as_new_rows(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path)
    jobs = AcquisitionJobs(store)
    job = advance(jobs, jobs.create(spec()), fixture_api(store, monkeypatch), 3)

    def overlap(req, response):
        response["data"] = [
            {"state": "PR", "period": "2026-01", "generation": 0},
            {"state": "PR", "period": "2026-03", "generation": 2},
        ]
        return response

    # A second job uses larger pages and receives duplicate records within one
    # captured page; raw bytes stay preserved but its checkpoint cannot advance.
    second = advance(jobs, jobs.create(spec(page_size=2)), fixture_api(store, monkeypatch), 3)
    failed = advance(jobs, second, fixture_api(store, monkeypatch, overlap))
    assert failed["error"] == "EIA_ROW_REPEATED" and failed["rows"] == 1
    assert jobs.get(job["job_id"])["rows"] == 1


def test_resumes_after_new_process_and_backups_preserve_offsets(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path / "live")
    jobs = AcquisitionJobs(store)
    api = fixture_api(store, monkeypatch)
    job = advance(jobs, jobs.create(spec()), api, 3)
    assert job["rows"] == 1 and job["status"] == "QUEUED"
    restored = tmp_path / "restore"
    restored.mkdir()
    for name in ["ledger.sqlite3", "acquisition.sqlite3"]:
        with (
            sqlite3.connect(store.root / name) as source,
            sqlite3.connect(restored / name) as backup,
        ):
            source.backup(backup)
    shutil.copytree(store.root / "raw", restored / "raw")
    restored_store = EvidenceStore(restored)
    resumed = AcquisitionJobs(restored_store)
    assert resumed.get(job["job_id"]) == job
    final = advance(resumed, job, fixture_api(restored_store, monkeypatch), 2)
    assert (final["rows"], final["total"], final["status"]) == (3, 3, "COMPLETE")
    assert jobs.get(job["job_id"])["rows"] == 1  # later writes do not alter the backup origin
    with sqlite3.connect(resumed.path) as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 11
    projection = electricity_projection(restored_store)
    assert len(projection["sources"]) == 5
    assert all(not state["measurements"] for state in projection["states"].values())
    assert all(
        hashlib.sha256(restored_store.read_raw(d)).hexdigest() == d for d in final["receipt_sha256"]
    )


def test_failure_retry_keeps_completed_pages_and_redacts_errors(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path)
    jobs = AcquisitionJobs(store)
    good = fixture_api(store, monkeypatch)
    job = advance(jobs, jobs.create(spec()), good, 3)
    bad = fixture_api(store, monkeypatch, lambda req, r: httpx.Response(503))
    failed = advance(jobs, job, bad)
    assert failed["status"] == "FAILED" and failed["rows"] == 1
    assert failed["error"] == "EIA_RETRY_EXHAUSTED"
    assert "synthetic-job-credential" not in json.dumps(failed)
    final = advance(AcquisitionJobs(store), failed, good, 2)
    assert final["status"] == "COMPLETE" and final["rows"] == 3


@pytest.mark.parametrize(
    "defect,code",
    [
        ("total", "EIA_PAGINATION_DRIFT"),
        ("scope", "EIA_ROW_SCOPE_INVALID"),
        ("repeat", "EIA_PAGE_REPEATED"),
        ("missing", "EIA_PAGE_INCOMPLETE"),
        ("month", "EIA_ROW_SCOPE_INVALID"),
    ],
)
def test_bad_pages_do_not_advance_checkpoint(tmp_path, monkeypatch, defect, code):
    store = EvidenceStore(tmp_path)
    jobs = AcquisitionJobs(store)
    job = advance(jobs, jobs.create(spec()), fixture_api(store, monkeypatch), 3)

    def mutate(req, response):
        if defect == "total":
            response["total"] = 4
        if defect == "scope":
            response["data"][0]["state"] = "TX"
        if defect == "repeat":
            response["data"][0] = {"state": "PR", "period": "2026-01", "generation": 0}
        if defect == "missing":
            response["data"] = []
        if defect == "month":
            response["data"][0]["period"] = "2026-00"
        return response

    failed = advance(jobs, job, fixture_api(store, monkeypatch, mutate))
    assert failed["status"] == "FAILED" and failed["error"] == code
    assert failed["rows"] == 1 and failed["receipt_sha256"] == job["receipt_sha256"]


def test_pr_unavailable_schema_drift_and_page_limits(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path)
    jobs = AcquisitionJobs(store)
    missing = fixture_api(
        store,
        monkeypatch,
        lambda req, r: (
            {"facets": [{"id": "TX"}], "totalFacets": "1"} if "/facet/" in req.url.path else r
        ),
    )
    job = advance(jobs, jobs.create(spec()), missing, 2)
    assert job["error"] == "EIA_PR_NOT_SUPPORTED" and job["rows"] == 0 and job["status"] == "FAILED"
    limited = advance(jobs, jobs.create(spec(max_pages=1)), fixture_api(store, monkeypatch), 4)
    assert limited["error"] == "EIA_PAGE_LIMIT" and limited["rows"] == 1
    unsupported = advance(
        jobs, jobs.create(spec(data_column="unknown")), fixture_api(store, monkeypatch)
    )
    assert unsupported["error"] == "EIA_ENDPOINT_SCHEMA_UNSUPPORTED"


def test_true_zero_has_a_complete_source_receipt_without_zero_generation(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path)
    jobs = AcquisitionJobs(store)
    api = fixture_api(
        store,
        monkeypatch,
        lambda req, r: {"total": 0, "data": []} if req.url.path.endswith("/data/") else r,
    )
    final = advance(jobs, jobs.create(spec()), api, 3)
    assert final["status"] == "COMPLETE" and final["total"] == final["rows"] == 0
    assert len(final["receipt_sha256"]) == 3
    assert electricity_projection(store)["states"]["OBSERVED"]["availability"] == "UNAVAILABLE"


def test_cancel_inflight_fences_worker_and_preserves_raw_evidence(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path)
    jobs = AcquisitionJobs(store)
    created = jobs.create(spec())

    def cancel(req, response):
        current = jobs.get(created["job_id"])
        jobs.cancel(created["job_id"], current["version"])
        return response

    with pytest.raises(JobConflict, match="LEASE_FENCED"):
        advance(jobs, created, fixture_api(store, monkeypatch, cancel))
    final = jobs.get(created["job_id"])
    assert final["status"] == "CANCELLED" and final["receipt_sha256"] == []
    assert len(store.snapshot()["sources"]) == 1
    with pytest.raises(JobConflict):
        advance(jobs, final, fixture_api(store, monkeypatch))


def test_crash_lease_expiry_concurrency_and_stale_commands(tmp_path, monkeypatch):
    now = [1000.0]
    store = EvidenceStore(tmp_path)
    jobs = AcquisitionJobs(store, clock=lambda: now[0])
    created = jobs.create(spec())

    def lease(_):
        try:
            return jobs._change(created["job_id"], created["version"]).version
        except JobConflict:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(lease, range(6)))
    assert outcomes.count(2) == 1 and outcomes.count("CONFLICT") == 5
    current = jobs.get(created["job_id"])
    with pytest.raises(JobConflict, match="ALREADY_RUNNING"):
        advance(jobs, current, fixture_api(store, monkeypatch))
    now[0] += 301
    assert advance(jobs, current, fixture_api(store, monkeypatch))["phase"] == "FACET"
    with pytest.raises(JobConflict):
        jobs.cancel(created["job_id"], current["version"])


def test_crash_after_source_capture_retries_without_skipping_page(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path)
    now = [1000.0]
    jobs = AcquisitionJobs(store, clock=lambda: now[0])
    api = fixture_api(store, monkeypatch)
    job = advance(jobs, jobs.create(spec()), api, 2)
    original = jobs._append

    def fail(db, state, previous):
        if state.rows:
            raise OSError("synthetic disk failure")
        original(db, state, previous)

    monkeypatch.setattr(jobs, "_append", fail)
    with pytest.raises(OSError):
        advance(jobs, job, api)
    assert jobs.get(job["job_id"])["rows"] == 0
    monkeypatch.setattr(jobs, "_append", original)
    now[0] += 301
    resumed = advance(jobs, jobs.get(job["job_id"]), api)
    assert resumed["rows"] == 1


def test_tampered_source_ledger_and_symlink_refused(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path)
    jobs = AcquisitionJobs(store)
    job = advance(jobs, jobs.create(spec()), fixture_api(store, monkeypatch))
    with sqlite3.connect(jobs.path) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM jobs")
    (store.root / "raw" / job["receipt_sha256"][0]).write_bytes(b"corruption")
    with pytest.raises(ValueError):
        jobs.get(job["job_id"])
    alias = tmp_path / "alias"
    alias.mkdir()
    (alias / "acquisition.sqlite3").symlink_to(jobs.path)
    with pytest.raises(ValueError):
        AcquisitionJobs(EvidenceStore(alias)).list()


@pytest.mark.parametrize(
    "updates",
    [
        {"endpoint": "other"},
        {"start": "2026-00"},
        {"end": "2025-01"},
        {"page_size": True},
        {"page_size": 5001},
        {"request_id": "../x"},
        {"api_key": "forbidden"},
        {"data_column": "x&api_key=x"},
    ],
)
def test_job_spec_negative_controls(updates):
    with pytest.raises(ValidationError):
        spec(**updates)


def test_real_api_auth_pagination_contract_and_corrupt_state(tmp_path, monkeypatch):
    from server.backend import electricity_api
    from server.backend.app import app

    monkeypatch.setattr(electricity_api.legacy, "DATA", tmp_path)
    client = TestClient(app)
    path = "/electricity/v1/acquisition-jobs"
    body = spec().model_dump(mode="json")
    assert client.get(path).json()["jobs"] == []
    monkeypatch.delenv("API_SECRET_KEY", raising=False)
    assert client.post(path, json=body).status_code == 503
    monkeypatch.setenv("API_SECRET_KEY", "synthetic-job-role")
    assert client.post(path, json=body).status_code == 401
    headers = {"Authorization": "Bearer synthetic-job-role"}
    job = client.post(path, json=body, headers=headers).json()
    second = client.post(path, json=spec().model_dump(mode="json"), headers=headers).json()
    result = client.get(path + "?limit=1").json()
    assert result["total"] == 2 and result["next_offset"] == 1
    assert client.get(path + "?offset=1&limit=1").json()["jobs"][0]["job_id"] == second["job_id"]
    schema = json.loads(
        (
            Path(__file__).parents[1] / "schemas/electricity_acquisition_jobs.v1.schema.json"
        ).read_text()
    )
    jsonschema.validate(result, schema)
    assert client.get(path + "/" + "f" * 32).status_code == 404
    assert client.get(path + "/bad").status_code == 422
    assert (
        client.post(
            path + "/" + job["job_id"] + "/cancel", json={"expected_version": 1}, headers=headers
        ).json()["status"]
        == "CANCELLED"
    )
    assert (
        client.post(
            path + "/" + job["job_id"] + "/step", json={"expected_version": 2}, headers=headers
        ).status_code
        == 409
    )
    with sqlite3.connect(tmp_path / "electricity/acquisition.sqlite3") as db:
        db.execute("DROP TRIGGER jobs_no_update")
        db.execute("UPDATE jobs SET digest='corrupt'")
    assert client.get(path).status_code == 503
