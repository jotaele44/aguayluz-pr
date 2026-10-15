import { expect, test } from '@playwright/test'

const backendUrl = 'http://127.0.0.1:8000'

function runtimeFailures(page) {
  const failures = []
  page.on('pageerror', (error) => failures.push(`page error: ${error.message}`))
  page.on('response', (response) => {
    if (response.status() >= 500) failures.push(`${response.status()} ${response.url()}`)
  })
  return failures
}

test('Drought Operations is discoverable and preserves official footprint semantics', async ({ page, request }) => {
  const failures = runtimeFailures(page)

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const link = page.locator('a[href="/drought"]').first()
  await expect(link).toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/drought\/?$/)
  await expect(page.getByRole('heading', { name: 'Puerto Rico Drought Operations' })).toBeVisible()
  await expect(page.getByText(/Percentages are cumulative area shares/)).toBeVisible()
  await expect(page.getByText(/No authoritative geospatial rationing feed/)).toBeVisible()

  const summaryResponse = await request.get(`${backendUrl}/drought/summary`)
  expect(summaryResponse.ok()).toBe(true)
  const summary = await summaryResponse.json()

  if (summary.status === 'available') {
    await expect(page.locator('[data-map-ready="true"]')).toHaveCount(1)
    await expect(page.getByRole('button', { name: 'Export PNG' })).toBeEnabled()
    expect(summary.statistics.semantics).toBe('cumulative_percent_area_at_or_above_category')

    const footprintResponse = await request.get(`${backendUrl}/drought/footprint.geojson`)
    expect(footprintResponse.ok()).toBe(true)
    const footprint = await footprintResponse.json()
    expect(footprint.features.length).toBeGreaterThan(0)
    for (const feature of footprint.features) {
      expect(['D0', 'D1', 'D2', 'D3', 'D4']).toContain(feature.properties.category)
      expect(feature.properties.derived).toBe(false)
    }
    expect(footprint.provenance.sha256).toMatch(/^[0-9a-f]{64}$/)
  } else {
    await expect(page.getByText('USDM footprint unavailable')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Export PNG' })).toBeDisabled()
  }

  expect(failures, failures.join('\n')).toEqual([])
})
