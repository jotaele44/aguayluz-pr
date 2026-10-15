import { promises as fs } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

const backendUrl = 'http://127.0.0.1:8000'
const artifactPath = fileURLToPath(new URL('../../data/drought_usdm_footprint.json', import.meta.url))

const E2E_ARTIFACT = {
  schema_version: 'aguayluz.usdm-drought-operations/v0.1',
  map_date: '2026-10-13',
  retrieved_at: '2026-10-15T20:00:00Z',
  authority: 'NDMC/USDM (USDA/NOAA/NASA partnership)',
  evidence_tier: 'T1',
  scope: 'Puerto Rico',
  statistics: {
    map_date: '2026-10-13',
    valid_start: '2026-10-13',
    valid_end: '2026-10-20',
    none_pct: 42.99,
    D0: 57.01,
    D1: 47.87,
    D2: 24.69,
    D3: 7.23,
    D4: 0,
    semantics: 'cumulative_percent_area_at_or_above_category',
  },
  history: [
    {
      map_date: '2026-10-06',
      D0: 55,
      D1: 44,
      D2: 22,
      D3: 5,
      D4: 0,
      semantics: 'cumulative_percent_area_at_or_above_category',
    },
    {
      map_date: '2026-10-13',
      D0: 57.01,
      D1: 47.87,
      D2: 24.69,
      D3: 7.23,
      D4: 0,
      semantics: 'cumulative_percent_area_at_or_above_category',
    },
  ],
  footprint: {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      id: 'D2-e2e',
      properties: {
        category: 'D2',
        source_category: 2,
        derived: false,
        selection_method: 'official_vector_component_pr_bbox_selection',
      },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [-67.2, 17.9],
          [-65.4, 17.9],
          [-65.4, 18.5],
          [-67.2, 18.5],
          [-67.2, 17.9],
        ]],
      },
    }],
  },
  source_manifestations: {
    geometry: {
      url: 'https://droughtmonitor.unl.edu/Data/json/USDM_20261013.json',
      sha256: 'a'.repeat(64),
      byte_count: 1,
      content_semantics: 'E2E contract fixture standing in for official date-specific USDM vector GeoJSON',
    },
    statistics: {
      url: 'https://usdmdataservices.unl.edu/',
      sha256: 'b'.repeat(64),
      byte_count: 1,
      content_semantics: 'E2E contract fixture standing in for official cumulative Puerto Rico area statistics',
    },
  },
  limitations: ['Browser-only contract fixture; never committed as production evidence.'],
}

function runtimeFailures(page) {
  const failures = []
  page.on('pageerror', (error) => failures.push(`page error: ${error.message}`))
  page.on('response', (response) => {
    if (response.status() >= 500) failures.push(`${response.status()} ${response.url()}`)
  })
  return failures
}

async function preserveExistingArtifact() {
  try {
    return await fs.readFile(artifactPath)
  } catch (error) {
    if (error?.code === 'ENOENT') return null
    throw error
  }
}

test('Drought Operations renders a populated source-bound map and exports a briefing PNG', async ({ page, request }) => {
  const failures = runtimeFailures(page)
  const previous = await preserveExistingArtifact()
  await fs.writeFile(artifactPath, JSON.stringify(E2E_ARTIFACT))

  try {
    const summaryResponse = await request.get(`${backendUrl}/drought/summary`)
    expect(summaryResponse.ok()).toBe(true)
    const summary = await summaryResponse.json()
    expect(summary.status).toBe('available')
    expect(summary.statistics.semantics).toBe('cumulative_percent_area_at_or_above_category')

    await page.goto('/', { waitUntil: 'domcontentloaded' })
    const link = page.locator('a[href="/drought"]').first()
    await expect(link).toBeVisible()
    await link.click()
    await expect(page).toHaveURL(/\/drought\/?$/)

    await expect(page.getByRole('heading', { name: 'Puerto Rico Drought Operations' })).toBeVisible()
    await expect(page.getByText(/Percentages are cumulative area shares/)).toBeVisible()
    await expect(page.getByText(/No authoritative geospatial rationing feed/)).toBeVisible()
    await expect(page.locator('[data-map-ready="true"]')).toHaveCount(1)

    const footprintResponse = await request.get(`${backendUrl}/drought/footprint.geojson`)
    expect(footprintResponse.ok()).toBe(true)
    const footprint = await footprintResponse.json()
    expect(footprint.features).toHaveLength(1)
    expect(footprint.features[0].properties.category).toBe('D2')
    expect(footprint.features[0].properties.derived).toBe(false)
    expect(footprint.provenance.sha256).toMatch(/^[0-9a-f]{64}$/)

    const exportButton = page.getByRole('button', { name: 'Export PNG' })
    await expect(exportButton).toBeEnabled()
    const downloadPromise = page.waitForEvent('download')
    await exportButton.click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe('aguayluz-drought-2026-10-13.png')

    expect(failures, failures.join('\n')).toEqual([])
  } finally {
    if (previous === null) await fs.rm(artifactPath, { force: true })
    else await fs.writeFile(artifactPath, previous)
  }
})
