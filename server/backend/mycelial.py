"""Research-only mycelial habitat assistant.

This module evaluates habitat-scale fungal fruiting conditions. It does not
provide precise locations, collection instructions, or access authorization.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/mycelial", tags=["mycelial"])

SENSITIVE_TERMS = {
    "psilocybe", "psilocybin", "cubensis", "magic mushroom", "hongos magicos",
    "hongos mágicos", "alucinogeno", "alucinógeno", "psychedelic", "psychoactive",
}
LOCATION_TERMS = {
    "coordenadas", "coordinate", "exact location", "ubicacion exacta", "ubicación exacta",
    "ruta", "route", "donde encontrar", "dónde encontrar", "where to find",
}
COLLECTION_TERMS = {
    "recolectar", "cosechar", "collect", "harvest", "consumir", "consume", "dosage", "dosis",
}


@dataclass(frozen=True)
class HabitatInputs:
    rain_72h_mm: float = 0.0
    humidity_pct: float = 70.0
    temperature_c: float = 24.0
    canopy_pct: float = 50.0
    soil_moisture_pct: float = 50.0
    organic_matter: str = "medium"
    wind_kph: float = 10.0
    access_status: str = "unknown"


def _contains_any(text: str, terms: set[str]) -> bool:
    normalized = text.casefold()
    return any(term.casefold() in normalized for term in terms)


def classify_query(query: str) -> dict[str, Any]:
    sensitive = _contains_any(query, SENSITIVE_TERMS)
    precise_location = _contains_any(query, LOCATION_TERMS)
    collection = _contains_any(query, COLLECTION_TERMS)
    if sensitive and (precise_location or collection):
        intent = "restricted_sensitive_taxon_request"
    elif sensitive:
        intent = "sensitive_taxon_ecology"
    elif precise_location:
        intent = "habitat_location_request"
    else:
        intent = "general_fungal_ecology"
    return {
        "intent": intent,
        "sensitive_taxon": sensitive,
        "precise_location_requested": precise_location,
        "collection_requested": collection,
    }


def score_habitat(values: HabitatInputs) -> tuple[int, list[str], list[str]]:
    score = 0
    favorable: list[str] = []
    unfavorable: list[str] = []

    if 15 <= values.rain_72h_mm <= 90:
        score += 22
        favorable.append("lluvia reciente suficiente")
    elif values.rain_72h_mm < 5:
        unfavorable.append("lluvia reciente insuficiente")
    else:
        unfavorable.append("lluvia excesiva o saturación posible")

    if values.humidity_pct >= 80:
        score += 18
        favorable.append("humedad ambiental alta")
    elif values.humidity_pct < 60:
        unfavorable.append("aire seco")

    if 18 <= values.temperature_c <= 28:
        score += 16
        favorable.append("temperatura moderada")
    else:
        unfavorable.append("temperatura fuera del rango moderado")

    if values.canopy_pct >= 60:
        score += 14
        favorable.append("dosel con sombra persistente")
    elif values.canopy_pct < 30:
        unfavorable.append("exposición solar elevada")

    if values.soil_moisture_pct >= 60:
        score += 16
        favorable.append("suelo húmedo")
    elif values.soil_moisture_pct < 35:
        unfavorable.append("suelo seco")

    if values.organic_matter.casefold() in {"high", "alta", "alto"}:
        score += 10
        favorable.append("materia orgánica abundante")
    elif values.organic_matter.casefold() in {"low", "baja", "bajo"}:
        unfavorable.append("poca materia orgánica")

    if values.wind_kph <= 15:
        score += 4
        favorable.append("viento bajo")
    elif values.wind_kph >= 30:
        unfavorable.append("viento fuerte")

    return min(score, 100), favorable, unfavorable


def suitability_label(score: int) -> str:
    if score >= 75:
        return "alta"
    if score >= 50:
        return "media"
    return "baja"


def weather_window(values: HabitatInputs, score: int) -> str:
    if score >= 75 and values.rain_72h_mm >= 15:
        return "Ventana ecológica favorable durante las próximas 24–72 horas, sujeta a acceso legal y verificación local."
    if score >= 50:
        return "Condiciones parciales; conviene reevaluar tras lluvia adicional o un aumento de humedad."
    return "No se observa una ventana favorable con los valores suministrados."


def access_filter(status: str) -> dict[str, str]:
    normalized = status.casefold()
    if normalized in {"public_open", "public-open", "open", "abierto"}:
        return {"status": "conditional", "message": "Acceso potencialmente público; confirme reglas, cierres y permisos vigentes."}
    if normalized in {"private", "restricted", "closed", "cerrado"}:
        return {"status": "blocked", "message": "No se recomienda entrada. El acceso está marcado como privado, restringido o cerrado."}
    return {"status": "unknown", "message": "Acceso no verificado. No use esta respuesta como autorización de entrada."}


def build_response(query: str, values: HabitatInputs) -> dict[str, Any]:
    classification = classify_query(query)
    score, favorable, unfavorable = score_habitat(values)
    access = access_filter(values.access_status)

    if classification["intent"] == "restricted_sensitive_taxon_request":
        return {
            "status": "restricted",
            "classification": classification,
            "answer": "Puedo explicar condiciones ecológicas generales, pero no proporcionar ubicaciones precisas, rutas, horarios operativos ni instrucciones de recolección para taxones activos o regulados.",
            "suitability": {"score": score, "label": suitability_label(score)},
            "favorable_conditions": favorable,
            "unfavorable_conditions": unfavorable,
            "weather_window": weather_window(values, score),
            "access": access,
            "spatial_resolution": "hábitat/provincia",
        }

    return {
        "status": "ok",
        "classification": classification,
        "answer": f"La idoneidad ecológica estimada es {suitability_label(score)} ({score}/100). La evaluación es de hábitat y no identifica puntos exactos ni autoriza acceso o recolección.",
        "suitability": {"score": score, "label": suitability_label(score)},
        "favorable_conditions": favorable,
        "unfavorable_conditions": unfavorable,
        "weather_window": weather_window(values, score),
        "access": access,
        "inputs": asdict(values),
        "spatial_resolution": "hábitat/provincia",
    }


@router.get("/health")
def mycelial_health() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "module": "PR_MYCELIAL_RUNTIME_MODULE",
        "mode": "research_only",
        "precise_sensitive_locations": "suppressed",
    })


@router.post("/query")
async def mycelial_query(request: Request) -> JSONResponse:
    body = await request.json()
    query = str(body.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query field required")
    raw = body.get("conditions") or {}
    try:
        values = HabitatInputs(
            rain_72h_mm=float(raw.get("rain_72h_mm", 0)),
            humidity_pct=float(raw.get("humidity_pct", 70)),
            temperature_c=float(raw.get("temperature_c", 24)),
            canopy_pct=float(raw.get("canopy_pct", 50)),
            soil_moisture_pct=float(raw.get("soil_moisture_pct", 50)),
            organic_matter=str(raw.get("organic_matter", "medium")),
            wind_kph=float(raw.get("wind_kph", 10)),
            access_status=str(raw.get("access_status", "unknown")),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid conditions payload") from exc
    return JSONResponse(build_response(query, values))
