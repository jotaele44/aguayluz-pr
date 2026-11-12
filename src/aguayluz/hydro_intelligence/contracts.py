"""Fail-closed Hydro source registry validation; not an operational scheduler."""
from __future__ import annotations

from urllib.parse import urlparse

DISCOVERABLE_TYPES = {"xlsx", "zip", "pdf"}
CONTRACT_ONLY_TYPES = {"regulatory_filing_or_native_workpaper", "vector_or_gis_container"}
REQUIRED_SOURCE_IDS = frozenset({
    "eia_860m", "eia_923", "luma_bps_daily", "prepa_hydroco", "pr_gis_water",
})
REQUIRED_FIELDS = {
    "source_id", "authority", "index_url", "artifact_type",
    "discovery_interval_hours", "periodicity", "identity_granularity",
    "ingest_role", "raw_byte_required", "certification",
}


def validate_source_contract(registry: dict) -> dict:
    """Validate registered sources without claiming acquisition or source identity."""
    if registry.get("schema_version") != "aguayluz.hydro-intelligence.source-registry/v1":
        raise ValueError("Unsupported source-registry schema version")
    if registry.get("implementation_state") != "CONTRACT_ONLY_NOT_RUNTIME":
        raise ValueError("Operational status cannot be inferred from this registry")
    sources = registry.get("source_families")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Source registry denominator missing")
    identifiers: set[str] = set()
    report = []
    for source in sources:
        if not isinstance(source, dict) or REQUIRED_FIELDS - source.keys():
            raise ValueError("Incomplete source registry contract")
        source_id = source["source_id"]
        if (not isinstance(source_id, str) or not source_id
                or not all(char.isalnum() or char in "_-" for char in source_id)
                or source_id in identifiers):
            raise ValueError("Invalid or duplicate source ID")
        identifiers.add(source_id)
        parsed = urlparse(source["index_url"])
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, 443)
                or parsed.fragment):
            raise ValueError("Invalid source index URL")
        interval = source["discovery_interval_hours"]
        if type(interval) is not int or not 1 <= interval <= 24 * 31:
            raise ValueError("Invalid bounded discovery interval")
        if source["raw_byte_required"] is not True:
            raise ValueError("Original source bytes are mandatory")
        kind = source["artifact_type"]
        if kind in DISCOVERABLE_TYPES:
            state = "DISCOVERY_ADAPTER_CONTRACT_ONLY"
        elif kind in CONTRACT_ONLY_TYPES:
            state = "SOURCE_SPECIFIC_ADAPTER_REQUIRED"
        else:
            raise ValueError("Unknown source artifact type")
        for field in ("authority", "periodicity", "identity_granularity",
                      "ingest_role", "certification"):
            if not isinstance(source[field], str) or not source[field].strip():
                raise ValueError("Empty required source metadata")
        report.append({"source_id": source_id, "adapter_state": state,
                       "acquisition_state": "NOT_ASSERTED"})
    if identifiers != REQUIRED_SOURCE_IDS:
        raise ValueError(
            "Unreviewed source population: "
            f"missing={sorted(REQUIRED_SOURCE_IDS - identifiers)}, "
            f"unexpected={sorted(identifiers - REQUIRED_SOURCE_IDS)}"
        )
    return {
        "state": "CONTRACT_ONLY_NOT_RUNTIME",
        "source_count": len(sources),
        "discovery_contract_count": sum(
            row["adapter_state"] == "DISCOVERY_ADAPTER_CONTRACT_ONLY"
            for row in report
        ),
        "source_specific_adapter_required_count": sum(
            row["adapter_state"] == "SOURCE_SPECIFIC_ADAPTER_REQUIRED"
            for row in report
        ),
        "sources": report,
        "operational_ingestion": False,
        "canonical_promotion": False,
    }
