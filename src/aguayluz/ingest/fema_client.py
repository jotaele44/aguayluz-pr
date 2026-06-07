"""HTTP client for the FEMA OpenFEMA Public Assistance dataset.

Public endpoint: https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails
No API key required. OData-style query syntax:
  ?$filter=stateAbbreviation eq 'PR' and damageCategoryCode eq 'F'
  ?$top=100&$skip=200
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("aguayluz.ingest.fema_client")

FEMA_PA_BASE_URL = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_PAGE_SIZE = 100
USER_AGENT = "aguayluz-pr/0.1 (+https://github.com/jotaele44/aguayluz-pr)"


class FEMAClientError(Exception):
    """Raised on non-retryable FEMA API failures."""


def _build_filter(
    *,
    state_abbr: str,
    damage_codes: list[str] | None = None,
    disaster_number: int | None = None,
) -> str:
    parts: list[str] = [f"stateAbbreviation eq '{state_abbr}'"]
    if damage_codes:
        if len(damage_codes) == 1:
            parts.append(f"damageCategoryCode eq '{damage_codes[0]}'")
        else:
            ors = " or ".join(f"damageCategoryCode eq '{c}'" for c in damage_codes)
            parts.append(f"({ors})")
    if disaster_number is not None:
        parts.append(f"disasterNumber eq {disaster_number}")
    return " and ".join(parts)


def fetch_public_assistance(
    *,
    state_abbr: str = "PR",
    damage_codes: list[str] | None = None,
    disaster_number: int | None = None,
    top: int = DEFAULT_PAGE_SIZE,
    skip: int = 0,
    include_metadata: bool = True,
    timeout: float = DEFAULT_TIMEOUT_S,
    max_retries: int = DEFAULT_MAX_RETRIES,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Hit FEMA OpenFEMA Public Assistance and return one page of records.

    Returns the raw envelope `{metadata: {...}, PublicAssistanceFundedProjectsDetails: [...]}`.
    """
    params: dict[str, str] = {
        "$filter": _build_filter(
            state_abbr=state_abbr,
            damage_codes=damage_codes,
            disaster_number=disaster_number,
        ),
        "$top": str(top),
        "$skip": str(skip),
    }
    if include_metadata:
        params["$metadata"] = "on"

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
    try:
        for attempt in range(max_retries + 1):
            response = client.get(FEMA_PA_BASE_URL, params=params)
            if response.status_code == 200:
                return response.json()
            if 500 <= response.status_code < 600 and attempt < max_retries:
                logger.warning("FEMA %s on attempt %d/%d; retrying", response.status_code, attempt + 1, max_retries)
                continue
            if response.status_code >= 400:
                raise FEMAClientError(
                    f"FEMA returned HTTP {response.status_code}: {response.text[:300]}"
                )
        raise FEMAClientError("FEMA client exhausted retry loop unexpectedly")
    finally:
        if owns_client:
            client.close()


def fetch_all_pa_records(
    *,
    state_abbr: str = "PR",
    damage_codes: list[str] | None = None,
    max_records: int = 500,
    page_size: int = DEFAULT_PAGE_SIZE,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Paginate FEMA OpenFEMA until `max_records` are gathered or the source dries up.

    Returns a single merged envelope (`PublicAssistanceFundedProjectsDetails: [...]`)
    so downstream `parse_fema_response()` can consume it unchanged.
    """
    collected: list[dict[str, Any]] = []
    skip = 0
    with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        while len(collected) < max_records:
            top = min(page_size, max_records - len(collected))
            envelope = fetch_public_assistance(
                state_abbr=state_abbr,
                damage_codes=damage_codes,
                top=top,
                skip=skip,
                include_metadata=False,
                client=client,
            )
            page = envelope.get("PublicAssistanceFundedProjectsDetails", []) or []
            if not page:
                break
            # Defensive trim: if the server ignores $top and overruns, don't
            # exceed the caller's max_records cap.
            room = max_records - len(collected)
            if len(page) > room:
                collected.extend(page[:room])
                break
            collected.extend(page)
            if len(page) < top:
                break
            skip += top
    return {
        "metadata": {
            "skip": 0,
            "top": len(collected),
            "filter": _build_filter(state_abbr=state_abbr, damage_codes=damage_codes),
            "format": "json",
            "metadata": True,
            "entityname": "PublicAssistanceFundedProjectsDetails",
            "version": "v2",
            "count": len(collected),
        },
        "PublicAssistanceFundedProjectsDetails": collected,
    }
