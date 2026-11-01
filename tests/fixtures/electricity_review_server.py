"""Browser-only synthetic candidates in a disposable runtime, never live data."""
import hashlib
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn

from aguayluz.electricity.evidence import GeneratorClaim, SourceReceipt
from aguayluz.electricity.store import EvidenceStore


def synthetic_job_client(store):
    """Test-only transport: never imported or installed by the application."""
    from aguayluz.electricity.eia import EIAClient
    failures = {"remaining": 4}
    def respond(request):
        if request.url.path.endswith("/data/"):
            offset = int(request.url.params["offset"])
            column = request.url.params["data[0]"]
            if column == "generation" and offset == 1 and failures["remaining"]:
                failures["remaining"] -= 1
                return httpx.Response(503)
            if column == "slow_generation":
                # Hold the synthetic response until the actual API revokes its
                # lease. This tests ordering, rather than a machine-speed race.
                from aguayluz.electricity.jobs import AcquisitionJobs
                ledger = AcquisitionJobs(store)
                active = [j["job_id"] for j in ledger.list()["jobs"]
                          if j["status"] == "RUNNING" and j["spec"]["data_column"] == column]
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if any(ledger.get(identifier)["status"] == "CANCELLED" for identifier in active):
                        break
                    time.sleep(0.05)
            data = {"total": "3", "data": [{"state": "PR", "period": f"2026-0{offset+1}", column: offset}]}
        elif "/facet/" in request.url.path:
            data = {"facets": [{"id": "PR"}], "totalFacets": "1"}
        else:
            data = {"facets": [{"id": "state"}], "frequency": [{"id": "monthly"}],
                    "data": {"generation": {}, "slow_generation": {}}}
        return httpx.Response(200, json={"response": data})
    return lambda _: EIAClient(store, client=httpx.Client(transport=httpx.MockTransport(respond)), sleep=lambda _: None)


def main():
    with tempfile.TemporaryDirectory(prefix="aguayluz-review-browser-") as directory:
        os.environ["AGUAYLUZ_DATA_HOME"] = directory
        os.environ["API_SECRET_KEY"] = "synthetic-browser-review-role"
        os.environ.pop("EIA_API_KEY", None)
        store = EvidenceStore(Path(directory) / "data" / "electricity")
        raw = b"SYNTHETIC BROWSER CANDIDATES; NOT AN OFFICIAL SOURCE OR TELEMETRY"
        digest = hashlib.sha256(raw).hexdigest()
        timestamp = datetime(2026, 10, 1, tzinfo=timezone.utc)
        store.capture(raw, SourceReceipt(sha256=digest, byte_count=len(raw),
                      source_url="https://www.eia.gov/electricity/data/eia860m/",
                      authority="SYNTHETIC BROWSER FIXTURE", retrieved_at=timestamp,
                      schema_signature="TEST_ONLY/SOURCE_CANDIDATE/AUDIT_ONLY"))
        claim = dict(source_system="EIA-860M", plant_id="1", generator_id="01",
                     valid_from=timestamp, name="SYNTHETIC BROWSER FIXTURE", status="OP",
                     nameplate_mw=1, receipt_sha256=digest)
        store.add_claims([GeneratorClaim(**claim), GeneratorClaim(**(claim | {"nameplate_mw": 2}))])
        # Synthetic credentials/transports are confined to this disposable test
        # process; the shipped application has no mock-provider switch.
        from aguayluz.electricity import jobs
        os.environ["EIA_API_KEY"] = "synthetic-browser-source-key"
        jobs.EIAClient = synthetic_job_client(store)
        uvicorn.run("server.backend.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
