"""NEON API v0 client for the NSF National Ecological Observatory Network.

Wraps https://data.neonscience.org/api/v0 for the four Puerto Rico sites in NEON
Domain D04 "Atlantic Neotropical": CUPE and GUIL (stream/aquatic) and GUAN and
LAJA (terrestrial).

The API splits in two, and the split shapes this whole integration:

* **Metadata is open.** ``/sites``, ``/products``, ``/locations`` and
  ``/releases`` answer 200 with no credential, and ``/sites/{code}`` already
  carries ``availableMonths[]`` per product — the entire publication-change
  signal, with nothing to download.
* **Bulk file manifests are gated.** ``/data/{product}/{site}/{month}`` returns
  HTTP 403 ``Access Denied`` to anonymous callers and needs a NEON API token.

See ``docs/NEON_INTEGRATION.md`` for the endpoint map and the product -> metric
table.
"""

from .client import NeonClient, resolve_token
from .errors import (
    NeonAccessDenied,
    NeonAuthError,
    NeonError,
    NeonRateLimitExceeded,
    NeonServerError,
)
from .health import check_health
from .mapping import (
    DEFERRED_PRODUCTS,
    NEON_EVIDENCE_TIER,
    NEON_LICENSE,
    NEON_OPERATOR,
    PR_DOMAIN_CODE,
    PR_SITE_CODES,
    PR_SITES,
    PRODUCT_METRICS,
    alert_module_for,
    sanitize_code,
    site_by_code,
)

__all__ = [
    "NeonClient",
    "resolve_token",
    "NeonError",
    "NeonAuthError",
    "NeonAccessDenied",
    "NeonRateLimitExceeded",
    "NeonServerError",
    "check_health",
    "PR_SITES",
    "PR_SITE_CODES",
    "PR_DOMAIN_CODE",
    "PRODUCT_METRICS",
    "DEFERRED_PRODUCTS",
    "NEON_EVIDENCE_TIER",
    "NEON_LICENSE",
    "NEON_OPERATOR",
    "alert_module_for",
    "sanitize_code",
    "site_by_code",
]
