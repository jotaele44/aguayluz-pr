"""EPA WATERS endpoint parameter map.

Do not assume one universal parameter style. The live OAS uses legacy p-prefix,
newer non-prefixed GET params, and p_ body fields depending on endpoint.
"""

BASE_URL = "https://api.epa.gov/waters"
FORMAT_PARAM = {"f": "json"}

ENDPOINT_PARAM_MAP = {
    "v1/drainageareadelineation": ["pgeometry", "pcomid", "pfeaturetype", "poutputflag"],
    "v3/drainageareadelineation": ["pgeometry", "pfeaturetype", "poutputflag"],
    "v1/