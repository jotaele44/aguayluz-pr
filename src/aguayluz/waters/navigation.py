"""Navigation adapter — WATERS-primary, pynhd-secondary.

Why split this way:
  - WATERS `/v4/upstreamdownstream` runs against NHDPlus V2.1 which definitively
    covers Puerto Rico (VPU 21). That makes it our **primary** navigation spine.
  - `pynhd` (HyRiver) wraps the USGS NLDI service plus StreamCat catchment
    attributes. NLDI's Puerto Rico coverage has been historically uncertain,
    so we **probe it once per process** and gate enrichment calls behind the
    result. If the probe fails or NLDI is unreachable, we never silently
    substitute mainland data — callers see `attribute_coverage="partial"` and
    a logged warning.
  - Even when NLDI is reachable, StreamCat metrics derived from VPU 21
    Vogel/VPUAttribute/NLCD extensions stay `"partial"` per the EPA inventory.
    The blocklist below mirrors the spec's load-bearing PR caveat.

This module deliberately stays small: trace helpers + probe + a thin enrichment
shim. Anything richer belongs in `aguayluz.analysis` (future).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Any

from .client import WatersClient
from .endpoints import upstream_downstream

logger = logging.getLogger("aguayluz.waters.navigation")

# A well-known PR mainland COMID used as a coverage canary.
# Sourced from the Lago La Plata pointindexing fixture in tests/.
_PR_PROBE_COMID = 21000100

# StreamCat-derived metric families that the EPA inventory marks as
# NOT AVAILABLE for VPU 21. Anything in this set returns `partial` even
# when pynhd works.
_VPU21_UNAVAILABLE_METRIC_PREFIXES = (
    "NLCD",            # National Land Cover Database derivatives
    "VogelEx",         # Vogel mean annual flow / velocity
    "VPUAttribute",    # VPU attribute extension
)


@dataclass(frozen=True)
class FlowlineSummary:
    """Minimal projection of a WATERS network flowline feature."""

    comid: int
    reachcode: str
    nhdplus_region: str | None
    gnis_name: str | None
    length_km: float | None


@dataclass(frozen=True)
class EnrichmentResult:
    """Outcome of an enrichment call. `value` is None when coverage is partial."""

    value: float | None
    attribute_coverage: str            # "full" or "partial"
    reason: str | None = None


# ---------------------------------------------------------------------------
# Tracing — WATERS-primary
# ---------------------------------------------------------------------------


def _project_features(resp: dict[str, Any]) -> list[FlowlineSummary]:
    fc = resp.get("network_flowlines") or {}
    features = fc.get("features") or []
    summaries: list[FlowlineSummary] = []
    for f in features:
        props = f.get("properties") or {}
        comid = props.get("comid")
        reachcode = props.get("reachcode")
        if comid is None or reachcode is None:
            continue
        summaries.append(
            FlowlineSummary(
                comid=int(comid),
                reachcode=str(reachcode),
                nhdplus_region=props.get("nhdplus_region"),
                gnis_name=props.get("gnis_name"),
                length_km=float(props["length_km"]) if "length_km" in props else None,
            )
        )
    return summaries


def trace_downstream(
    client: WatersClient,
    *,
    comid: int,
    distance_km: float,
    include_tributaries: bool = False,
) -> list[FlowlineSummary]:
    """Trace flow downstream of `comid` for `distance_km` along the network."""
    direction = "DM" if include_tributaries else "DD"
    resp = upstream_downstream(client, comid=comid, distance_km=distance_km, direction=direction)
    return _project_features(resp)


def trace_upstream(
    client: WatersClient,
    *,
    comid: int,
    distance_km: float,
    include_tributaries: bool = True,
) -> list[FlowlineSummary]:
    """Trace flow upstream of `comid`. Defaults to including tributaries (UT)."""
    direction = "UT" if include_tributaries else "UM"
    resp = upstream_downstream(client, comid=comid, distance_km=distance_km, direction=direction)
    return _project_features(resp)


# ---------------------------------------------------------------------------
# pynhd enrichment — gated by NLDI/PR coverage probe
# ---------------------------------------------------------------------------


def _default_nldi_probe(comid: int) -> bool:
    """Default probe: does `pynhd.NLDI` return a feature for the PR COMID?

    Wrapped in try/except so any failure (network, import, unsupported feature
    source) lands as "no PR coverage" rather than crashing.
    """
    try:
        from pynhd import NLDI

        nldi = NLDI()
        gdf = nldi.getfeature_byid("comid", str(comid))
        return gdf is not None and len(gdf) > 0
    except Exception as exc:  # noqa: BLE001 — third-party may raise broadly
        logger.warning("pynhd NLDI PR probe failed; treating as no coverage: %s", exc)
        return False


# Module-level singleton holders so tests can override the probe deterministically.
_probe_fn: Callable[[int], bool] = _default_nldi_probe


def set_nldi_probe(fn: Callable[[int], bool]) -> None:
    """Override the probe (tests). Pass `_default_nldi_probe` to reset."""
    global _probe_fn
    _probe_fn = fn
    nldi_has_pr.cache_clear()


@cache
def nldi_has_pr() -> bool:
    """Cached one-shot probe — does NLDI return data for a known PR COMID?"""
    ok = _probe_fn(_PR_PROBE_COMID)
    if not ok:
        logger.warning(
            "pynhd NLDI has no PR coverage; StreamCat enrichment will return "
            "attribute_coverage='partial' for all PR COMIDs."
        )
    return ok


def _is_vpu21_unavailable_metric(metric: str) -> bool:
    return any(metric.startswith(p) for p in _VPU21_UNAVAILABLE_METRIC_PREFIXES)


def enrich_streamcat(
    comid: int,
    metric: str,
    *,
    nhdplus_region: str | None = None,
    fetch_fn: Callable[[int, str], float | None] | None = None,
) -> EnrichmentResult:
    """Look up a StreamCat metric for a COMID, honoring VPU 21 gaps.

    `fetch_fn(comid, metric)` is the StreamCat fetcher — a function so tests
    can stub it. The default fetcher calls `pynhd.streamcat`.

    Returns partial coverage when:
      - the NLDI/PR probe failed, OR
      - the metric belongs to a VPU 21 unavailable dataset AND nhdplus_region=="21".
    """
    if nhdplus_region == "21" and _is_vpu21_unavailable_metric(metric):
        return EnrichmentResult(
            value=None,
            attribute_coverage="partial",
            reason=f"metric {metric!r} unavailable for VPU 21 per EPA inventory",
        )

    if not nldi_has_pr():
        return EnrichmentResult(
            value=None,
            attribute_coverage="partial",
            reason="pynhd NLDI has no PR coverage",
        )

    if fetch_fn is None:
        fetch_fn = _default_streamcat_fetch

    try:
        value = fetch_fn(comid, metric)
    except Exception as exc:  # noqa: BLE001
        logger.warning("StreamCat fetch failed for comid=%s metric=%s: %s", comid, metric, exc)
        return EnrichmentResult(value=None, attribute_coverage="partial", reason=str(exc))

    return EnrichmentResult(value=value, attribute_coverage="full")


def _default_streamcat_fetch(comid: int, metric: str) -> float | None:
    """Default StreamCat fetcher using pynhd."""
    from pynhd import streamcat

    df = streamcat(comid_ids=[comid], metric_names=[metric])
    if df is None or len(df) == 0:
        return None
    row = df.iloc[0]
    val = row.get(metric)
    return float(val) if val is not None else None
