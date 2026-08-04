"""Read-only HTTP acquisition with raw-byte receipts."""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .model import (
    FetchReceipt,
    NEON_SITE,
    USER_AGENT,
    safe_slug,
    sha256_bytes,
    utcnow,
)


def request_url(
    *,
    source_id: str,
    provider: str,
    url: str,
    output_dir: Path,
    extra_headers: dict[str, str] | None = None,
    timeout_s: float = 45.0,
) -> tuple[FetchReceipt, bytes]:
    headers = {"Accept": "*/*", "User-Agent": USER_AGENT}
    headers.update(extra_headers or {})
    request = urllib.request.Request(url, headers=headers)
    status: int | None = None
    response_headers: Any = {}
    error: str | None = None
    body = b""
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            status = int(response.status)
            response_headers = response.headers
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        response_headers = exc.headers or {}
        body = exc.read()
        error = f"HTTPError:{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        error = f"{type(exc).__name__}:{str(exc)[:240]}"

    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_name = f"{safe_slug(source_id)}_{sha256_bytes(url.encode('utf-8'))[:12]}.bin"
    raw_path = raw_dir / raw_name
    raw_path.write_bytes(body)
    return (
        FetchReceipt(
            source_id=source_id,
            provider=provider,
            url=url,
            retrieved_at=utcnow().isoformat(),
            http_status=status,
            content_type=response_headers.get("Content-Type") if response_headers else None,
            etag=response_headers.get("ETag") if response_headers else None,
            last_modified=response_headers.get("Last-Modified") if response_headers else None,
            byte_count=len(body),
            sha256=sha256_bytes(body),
            raw_path=raw_path.relative_to(output_dir).as_posix(),
            error=error,
        ),
        body,
    )


def usgs_iv_url(site_ids: Iterable[str]) -> str:
    query = urllib.parse.urlencode(
        {
            "format": "json",
            "sites": ",".join(site_ids),
            "period": "P7D",
            "siteStatus": "all",
        }
    )
    return f"https://waterservices.usgs.gov/nwis/iv/?{query}"


def usgs_ogc_url(collection: str, site_id: str, *, limit: int = 1000) -> str:
    query = urllib.parse.urlencode(
        {
            "f": "json",
            "monitoring_location_id": f"USGS-{site_id}",
            "limit": str(limit),
        }
    )
    return f"https://api.waterdata.usgs.gov/ogcapi/v0/collections/{collection}/items?{query}"


def wqx3_url(site_id: str, now: datetime) -> str:
    query = urllib.parse.urlencode(
        {
            "siteid": f"USGS-{site_id}",
            "startDateLo": (now - timedelta(days=45)).strftime("%m-%d-%Y"),
            "mimeType": "csv",
        }
    )
    return f"https://www.waterqualitydata.us/wqx3/Result/search?{query}"


def neon_site_url() -> str:
    return f"https://data.neonscience.org/api/v0/sites/{NEON_SITE}"


def neon_data_url(product: str, month: str) -> str:
    return f"https://data.neonscience.org/api/v0/data/{product}/{NEON_SITE}/{month}"
