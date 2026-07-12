# PR Mycelial Runtime Module

## Purpose

The module evaluates habitat-scale fungal fruiting conditions from user-supplied environmental variables. It is a research and ecological-planning surface, not a locator, access authorization, collection guide, or permit.

## Backend

Development entrypoint:

```bash
uvicorn server.backend.main_mycelial:app --reload --port 8000
```

Endpoints:

- `GET /mycelial/health`
- `POST /mycelial/query`

Example request:

```json
{
  "query": "¿Qué condiciones favorecen hongos saprófitos?",
  "conditions": {
    "rain_72h_mm": 30,
    "humidity_pct": 88,
    "temperature_c": 24,
    "canopy_pct": 80,
    "soil_moisture_pct": 72,
    "organic_matter": "high",
    "wind_kph": 6,
    "access_status": "unknown"
  }
}
```

## Runtime functions

- Query classifier
- Habitat suitability score
- Ecological weather window
- Access-status filter
- Explainability factors
- Sensitive-taxon sanitizer

## Safety and release controls

Requests combining active or regulated taxa with precise-location, route, collection, consumption, or dosage language are restricted. The response remains at habitat/province resolution and does not provide operational directions.

Access status defaults to `unknown`. The system never treats a model output as permission to enter private, protected, restricted, or closed land.

## Dashboard

The React dashboard exposes the module at:

```text
/mycelial
```

The first runtime release accepts environmental values entered by the user. A later phase can attach an authoritative weather adapter and official access layers without changing the public response contract.
