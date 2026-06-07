"""EPA Facility Registry Service (FRS) adapter.

Public source: https://frs-public.epa.gov/ords/frs_public2/frs_rest_services.get_facilities
- No API key required.
- State + city + program filters supported.
- Returns `{"Results": {"FRSFacility": [...]}}` JSON.

We parse the response, classify each facility's likely asset_type by name
heuristics, and emit `FacilitySeed` records. Non-utility records (hospitals,
apartments, generic industrial) get `is_utility=False` so the pipeline skips
them with an audit trail.
"""

from __future__ import annotations

from typing import Any

from ..models import AssetType
from .pipeline import FacilitySeed

FRS_PROVENANCE = "EPA Facility Registry Service (FRS)"


def _f(value: Any) -> float | None:
    """Parse a string-or-None lat/lon field into a float or None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def infer_asset_type(name: str) -> tuple[AssetType, str, bool]:
    """Heuristic classifier: (asset_type, asset_subtype, is_utility).

    Order matters — more specific keywords are checked first so
    'WATER TREATMENT' beats a bare 'WATER' match.
    """
    upper = name.upper()

    # Power infrastructure first (least ambiguous keywords).
    if "SUBSTATION" in upper or "SUBESTACION" in upper:
        return "power", "substation", True
    if any(kw in upper for kw in ("POWER PLANT", "GENERATING", "PLANTA GENERADORA")):
        return "power", "generation_plant", True
    if "TRANSMISSION" in upper:
        return "power", "transmission_line", True

    # Wastewater before water — "WASTEWATER" contains "WATER".
    if any(kw in upper for kw in ("WWTP", "WASTEWATER", "AGUAS RESIDUALES", "SEWAGE")):
        return "wastewater", "treatment_plant", True

    if any(kw in upper for kw in ("WATER TREATMENT", "WTP", "PLANTA DE AGUA", "AQUEDUCT")):
        return "water", "treatment_plant", True
    if any(kw in upper for kw in ("PUMP STATION", "PUMP STA", "EBAR")):
        return "water", "pump_station", True
    if "RESERVOIR" in upper or "EMBALSE" in upper or upper.startswith("LAGO "):
        return "water", "reservoir", True

    if any(kw in upper for kw in ("CELL TOWER", "CELLULAR", "TELECOM")):
        return "telecom", "tower", True

    return "unknown", "facility", False


def parse_frs_response(response: dict[str, Any]) -> list[FacilitySeed]:
    """Parse an FRS REST envelope `{Results: {FRSFacility: [...]}}` into seeds."""
    facilities = response.get("Results", {}).get("FRSFacility", []) or []
    seeds: list[FacilitySeed] = []
    for f in facilities:
        name = (f.get("FacilityName") or "").strip()
        municipality = (f.get("CityName") or "").strip() or "Unknown"
        registry_id = f.get("RegistryId") or ""
        if not registry_id:
            continue  # FRS guarantees this; skip if absent.

        asset_type, asset_subtype, is_utility = infer_asset_type(name)
        seeds.append(
            FacilitySeed(
                seed_id=f"AYL_AST_FRS_{registry_id}",
                name=name or registry_id,
                municipality=municipality.title(),
                asset_type=asset_type,
                asset_subtype=asset_subtype,
                lat=_f(f.get("Latitude83")),
                lon=_f(f.get("Longitude83")),
                operator=None,  # FRS lacks an explicit operator field at this layer
                source_provenance=f"{FRS_PROVENANCE} RegistryId={registry_id}",
                is_utility=is_utility,
            )
        )
    return seeds
