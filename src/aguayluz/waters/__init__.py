"""WATERS REST API client for the U.S. EPA Office of Water.

Wraps https://api.epa.gov/waters (gated by api.data.gov). Only the 8 modern
endpoints are used in v1 of this module — legacy navigation/watershedsp/
nhdplus_feature endpoints exist on the same gateway but are out-of-scope by
choice for the federation module's MVP.

See AGUAYLUZ_PR_SKILL.md and the build plan for the rationale.
"""

from .client import WatersClient
from .errors import AuthError, RateLimitExceeded, WatersError, WatersServerError

__all__ = [
    "WatersClient",
    "AuthError",
    "RateLimitExceeded",
    "WatersError",
    "WatersServerError",
]
