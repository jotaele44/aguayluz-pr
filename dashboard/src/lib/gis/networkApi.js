// AguaYLuz-only client for the dependency endpoints (not mirrored from spiderweb-pr):
//   GET  /gis/trace     -> recorded dependency links from a feature, with per-hop link evidence
//   POST /gis/scenario  -> gis-scenario-result/1.0 (always HYPOTHESIS, never persisted)
//   GET  /gis/layers/asset_dependencies.geojson -> the links as LineStrings (for highlighting)
// See docs/GIS_VIEWER_API.md. Proxy links (evidence_required) must be labelled wherever
// a result that used them is shown.

export const PROXY_LABEL = 'Proximity proxy, not a verified circuit'

async function readJson(response) {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = `${detail}: ${body.detail}`
    } catch { /* non-JSON error body */ }
    throw new Error(detail)
  }
  return response.json()
}

export function createNetworkClient(apiBase, fetchImpl = fetch) {
  return {
    async trace(featureId, direction = 'downstream', maxHops = 25) {
      const params = new URLSearchParams({ feature_id: featureId, direction, max_hops: String(maxHops) })
      return readJson(await fetchImpl(`${apiBase}/gis/trace?${params.toString()}`))
    },
    async scenario(selected, maxHops = 25) {
      return readJson(await fetchImpl(`${apiBase}/gis/scenario`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected, max_hops: maxHops }),
      }))
    },
    async dependencyLines() {
      return readJson(await fetchImpl(`${apiBase}/gis/layers/asset_dependencies.geojson`))
    },
  }
}

/** The dependency lines a trace or scenario actually used, for map highlighting. */
export function linesForEdges(collection, edgeIds) {
  const wanted = new Set(edgeIds)
  return {
    type: 'FeatureCollection',
    features: (collection?.features ?? []).filter((feature) => wanted.has(feature.properties?.edge_id)),
  }
}

/** One-line summary of path evidence for a trace hit or impacted feature. */
export function evidenceText(item) {
  const confidence = typeof item.confidence === 'number' ? `${Math.round(item.confidence)}%` : 'unknown'
  return `${item.relation ?? 'link'} · confidence ${confidence}${item.evidence_required ? ` · ${PROXY_LABEL}` : ''}`
}
