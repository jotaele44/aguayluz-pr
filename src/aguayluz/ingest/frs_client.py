"""HTTP client for the EPA Facility Registry Service (FRS).

Public endpoint: https://frs-public.epa.gov/ords/frs_public2/frs_rest_services.get_facilities
No API key required. The service requires at least one search criterion alongside
state_abbr (it returns 400 otherwise — empirically confirmed in M5 exploration).

Pagination: FRS doesn't expose page tokens, but the response includes all matching
records up to a server-side cap (~10k). For large queries pass narrow filters
(city_name, county_name, program_acrnm).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import httpx

logger = logging.getLogger("aguayluz.ingest.frs_client")

FRS_BASE_URL = "https://frs-public.epa.gov/ords/frs_public2/frs_rest_services.get_facilities"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_RETRIES = 2
USER_AGENT = "aguayluz-pr/0.1 (+https://github.com/jotaele44/aguayluz-pr)"


class FRSClientError(Exception):
    """Raised on non-retryable FRS API failures (4xx other than 429)."""


def fetch_facilities(
    *,
    state_abbr: str,
    city_name: str | None = None,
    county_name: str | None = None,
    program_acrnm: str | None = None,
    zip_code: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    max_retries: int = DEFAULT_MAX_RETRIES,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Hit FRS and return the raw `{"Results": {"FRSFacility": [...]}}` envelope.

    At least one of city_name/county_name/program_acrnm/zip_code must be set,
    otherwise FRS returns 400 ("search parameters not provided").
    """
    if not any((city_name, county_name, program_acrnm, zip_code)):
        raise FRSClientError(
            "FRS requires at least one of city_name/county_name/program_acrnm/zip_code "
            f"alongside state_abbr={state_abbr!r}"
        )

    params: dict[str, str] = {"state_abbr": state_abbr, "output": "JSON"}
    if city_name:
        params["city_name"] = city_name
    if county_name:
        params["county_name"] = county_name
    if program_acrnm:
        params["pgm_sys_acrnm"] = program_acrnm
    if zip_code:
        params["zip_code"] = zip_code

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
    try:
        for attempt in range(max_retries + 1):
            response = client.get(FRS_BASE_URL, params=params)
            if response.status_code == 200:
                return response.json()
            if 500 <= response.status_code < 600 and attempt < max_retries:
                logger.warning("FRS %s on attempt %d/%d; retrying", response.status_code, attempt + 1, max_retries)
                continue
            if response.status_code >= 400:
                raise FRSClientError(
                    f"FRS returned HTTP {response.status_code}: {response.text[:300]}"
                )
        # defensive — loop should always return or raise above
        raise FRSClientError("FRS client exhausted retry loop unexpectedly")
    finally:
        if owns_client:
            client.close()


def fetch_all_pr_facilities(
    *,
    cities: Iterable[str] | None = None,
    counties: Iterable[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> list[dict[str, Any]]:
    """Convenience: fetch FRS records across multiple PR localities and merge.

    Dedupes by RegistryId since the same facility can appear in both city and
    county pulls.
    """
    seen: dict[str, dict[str, Any]] = {}
    queries: list[dict[str, str]] = []
    for city in cities or []:
        queries.append({"city_name": city})
    for county in counties or []:
        queries.append({"county_name": county})
    if not queries:
        raise FRSClientError("fetch_all_pr_facilities requires at least one city or county")

    with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        for q in queries:
            resp = fetch_facilities(state_abbr="PR", client=client, **q)  # type: ignore[arg-type]
            for f in resp.get("Results", {}).get("FRSFacility", []):
                rid = f.get("RegistryId")
                if rid and rid not in seen:
                    seen[rid] = f
    return list(seen.values())
