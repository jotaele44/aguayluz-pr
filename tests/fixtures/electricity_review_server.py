"""Browser-only synthetic candidates in a disposable runtime, never live data."""
import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import uvicorn

from aguayluz.electricity.evidence import GeneratorClaim, SourceReceipt
from aguayluz.electricity.store import EvidenceStore


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
        uvicorn.run("server.backend.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
