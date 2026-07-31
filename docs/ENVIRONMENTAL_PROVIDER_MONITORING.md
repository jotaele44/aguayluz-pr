# Environmental provider monitoring

AguaYLuz treats external environmental systems as authoritative upstream providers, not as mutable local truth. This phase adds a fail-closed provider registry and metadata-health poller for:

- NSF NEON (`GUAN`, `LAJA`, `CUPE`, `GUIL`)
- USGS Water Data APIs
- NOAA/NWS
- NASA Earthdata collections relevant to GPM and SMAP
- Luquillo LTER / U.S. Forest Service
- EPA Water Quality Portal
- Puerto Rico DRNA hydrology sources

## Security contract

The NEON token is read from `NEON_API_TOKEN`. It is sent only through the documented `X-API-Token` request header. The value is never returned, logged, serialized, hashed into receipts, or written into snapshots. `.env` is already excluded by the repository runtime-data policy.

External polling is disabled unless:

```sh
AGUAYLUZ_EXTERNAL_POLLING_ENABLED=true
```

This preserves shadow-mode operation and prevents tests, desktop startup, or ordinary API reads from unexpectedly using the network.

## API

- `GET /environmental-providers` — registry and Puerto Rico NEON site inventory.
- `GET /environmental-providers/health` — configuration-only status; no network access.
- `GET /environmental-providers/health?live=true` — live metadata health checks, still gated by the environment flag.
- `POST /environmental-providers/poll?persist=true` — writes a secret-free, content-hashed snapshot under runtime `data/`.

## Delta semantics

A provider is marked changed only when a successful response produces a SHA-256 digest different from its previous successful snapshot. Errors, disabled polling, and missing credentials cannot masquerade as data changes.

## Current boundary

This phase monitors provider availability and metadata payload changes. It does **not** yet ingest or normalize scientific observations, issue live notifications, or promote external readings into certified AguaYLuz series. Those actions require provider-specific schemas, completeness accounting, QA/QC interpretation, and replay tests.
