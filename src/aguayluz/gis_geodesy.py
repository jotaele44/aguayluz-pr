"""WGS84 validation and geodesic distance for the GIS viewer modules.

Ported unchanged in behaviour from ``federation/spatial_core.py`` (the
federation spatial core at the repository root, which is not part of the
installed ``aguayluz`` package) so ``aguayluz.gis_query`` -- a mirror of
spiderweb-pr's ``spiderweb/gis_query.py`` -- can import it from inside the
package. Vincenty inverse on the WGS84 ellipsoid with a haversine fallback.
"""

from __future__ import annotations

import math

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_B = (1 - WGS84_F) * WGS84_A


def validate_lon_lat(lon: float, lat: float) -> tuple[float, float]:
    lon, lat = float(lon), float(lat)
    if (
        not math.isfinite(lon)
        or not math.isfinite(lat)
        or not -180 <= lon <= 180
        or not -90 <= lat <= 90
    ):
        raise ValueError(f"invalid WGS84 coordinate: {(lon, lat)}")
    return lon, lat


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    lon1, lat1 = validate_lon_lat(lon1, lat1)
    lon2, lat2 = validate_lon_lat(lon2, lat2)
    p1, p2 = map(math.radians, (lat1, lat2))
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371008.8 * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0, 1 - h)))


def geodesic_distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    lon1, lat1 = validate_lon_lat(lon1, lat1)
    lon2, lat2 = validate_lon_lat(lon2, lat2)
    if (lon1, lat1) == (lon2, lat2):
        return 0.0
    p1, p2 = map(math.radians, (lat1, lat2))
    U1 = math.atan((1 - WGS84_F) * math.tan(p1))
    U2 = math.atan((1 - WGS84_F) * math.tan(p2))
    L = math.radians(lon2 - lon1)
    lam = L
    for _ in range(200):
        sl, cl = math.sin(lam), math.cos(lam)
        ss = math.hypot(
            math.cos(U2) * sl, math.cos(U1) * math.sin(U2) - math.sin(U1) * math.cos(U2) * cl
        )
        if ss == 0:
            return 0.0
        cs = math.sin(U1) * math.sin(U2) + math.cos(U1) * math.cos(U2) * cl
        sigma = math.atan2(ss, cs)
        sa = math.cos(U1) * math.cos(U2) * sl / ss
        c2a = 1 - sa * sa
        c2sm = 0.0 if c2a == 0 else cs - 2 * math.sin(U1) * math.sin(U2) / c2a
        C = WGS84_F / 16 * c2a * (4 + WGS84_F * (4 - 3 * c2a))
        nxt = L + (1 - C) * WGS84_F * sa * (
            sigma + C * ss * (c2sm + C * cs * (-1 + 2 * c2sm * c2sm))
        )
        if abs(nxt - lam) < 1e-12:
            break
        lam = nxt
    else:
        return _haversine_m(lon1, lat1, lon2, lat2)
    u2 = c2a * (WGS84_A**2 - WGS84_B**2) / (WGS84_B**2)
    A = 1 + u2 / 16384 * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
    B = u2 / 1024 * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))
    ds = (
        B
        * ss
        * (
            c2sm
            + B
            / 4
            * (
                cs * (-1 + 2 * c2sm * c2sm)
                - B / 6 * c2sm * (-3 + 4 * ss * ss) * (-3 + 4 * c2sm * c2sm)
            )
        )
    )
    return WGS84_B * A * (sigma - ds)
