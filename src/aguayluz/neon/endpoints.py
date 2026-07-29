"""NEON API v0 endpoint map.

Split by authentication requirement, because the split is not obvious and drove
the whole design of this integration (see ``docs/NEON_INTEGRATION.md``):

**Open — HTTP 200 with no credential**
    ``/sites``, ``/sites/{code}``, ``/products``, ``/products/{code}``,
    ``/locations/{code}``, ``/releases``, ``/releases/{name}``

**Gated — HTTP 403 ``Access Denied`` with no credential**
    ``/data/{productCode}/{siteCode}/{month}``

Paths are returned relative to :data:`DEFAULT_BASE_URL` so
:class:`~aguayluz.neon.client.NeonClient` can join them.
"""

from __future__ import annotations

DEFAULT_BASE_URL = "https://data.neonscience.org/api/v0"

#: The NEON API version this module speaks. Recorded in provenance rows.
API_VERSION = "v0"

# ── open endpoints ────────────────────────────────────────────────────────────
SITES = "/sites"
PRODUCTS = "/products"
RELEASES = "/releases"


def site(site_code: str) -> str:
    """Site detail: metadata + ``dataProducts[]`` with ``availableMonths[]``."""
    return f"/sites/{site_code}"


def product(product_code: str) -> str:
    """Data-product metadata (title, science team, themes, keywords)."""
    return f"/products/{product_code}"


def location(location_code: str) -> str:
    """Named-location detail (site, tower, plot, sensor position)."""
    return f"/locations/{location_code}"


def release(release_name: str) -> str:
    """Release detail (generation date + signed manifest artifacts)."""
    return f"/releases/{release_name}"


# ── gated endpoints ───────────────────────────────────────────────────────────
def data_manifest(product_code: str, site_code: str, month: str) -> str:
    """File manifest for one product/site/month.

    ``month`` is ``YYYY-MM``. Requires a NEON API token: anonymous callers get
    HTTP 403 ``Access Denied`` from NEON's own gateway.
    """
    return f"/data/{product_code}/{site_code}/{month}"


#: Endpoint prefixes known to require a token, for clearer error messages.
GATED_PREFIXES: tuple[str, ...] = ("/data/",)


def is_gated(path: str) -> bool:
    """True when ``path`` is known to require a NEON API token."""
    return path.startswith(GATED_PREFIXES)
