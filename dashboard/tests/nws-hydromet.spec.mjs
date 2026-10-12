import { expect, test } from '@playwright/test'

const backendUrl = 'http://127.0.0.1:8000'

function trackRuntimeFailures(page) {
  const failures = []
  page.on('pageerror', (error) => failures.push(`page error: ${error.message}`))
  page.on('response', (response) => {
    if (response.status() >= 500) failures.push(`${response.status()} ${response.url()}`)
  })
  return failures
}

test('NWS Hydromet is reachable from the sidebar and shows freshness, provenance and gauges', async ({ page, request }) => {
  const failures = trackRuntimeFailures(page)

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const link = page.locator('a[href="/hydromet"]').first()
  await expect(link).toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/hydromet\/?$/)

  await expect(page.getByRole('heading', { name: 'NWS Hydromet' })).toBeVisible()
  await expect(page.getByRole('note', { name: 'Hydromet scope' })).toContainText(/not confirmed damage/i)

  const card = page.getByTestId('hydromet-source-nwps_gauges')
  await expect(card).toBeVisible()
  await expect(card.getByText(/^(FRESH|STALE|FAILED|NEVER)$/)).toBeVisible()
  await expect(card.getByRole('button', { name: /refresh now/i })).toBeVisible()

  const table = page.getByRole('table', { name: 'NWPS river gauges' })
  await expect(table).toBeVisible()
  expect(await table.locator('tbody tr').count()).toBeGreaterThan(0)

  const filter = page.getByRole('button', { name: /show only gauges in flood/i })
  await filter.click()
  await expect(page.getByRole('button', { name: /showing gauges in flood/i })).toHaveAttribute('aria-pressed', 'true')

  const summary = await (await request.get(`${backendUrl}/hydromet/summary`)).json()
  expect(summary.scope.completeness_claimed).toBe(false)
  expect(summary.integrity.state).toBe('PASS')
  expect(summary.counts.gauges).toBeGreaterThan(0)

  const sources = await (await request.get(`${backendUrl}/hydromet/sources`)).json()
  const nwps = sources.sources.find((s) => s.source_id === 'nwps_gauges')
  expect(nwps.receipt.last_success.byte_sha256).toMatch(/^[0-9a-f]{64}$/)

  expect(failures, failures.join('\n')).toEqual([])
})

test('river gauges layer toggles on the map without runtime errors', async ({ page }) => {
  const failures = trackRuntimeFailures(page)
  await page.goto('/map', { waitUntil: 'domcontentloaded' })
  const toggle = page.getByRole('button', { name: /^River gauges \d+$/ })
  await expect(toggle).toBeVisible()
  await toggle.click()
  await expect(page.getByText('River gauges (NWS NWPS)')).toBeVisible()
  expect(failures, failures.join('\n')).toEqual([])
})

// 1×1 transparent PNG: the CloudGIS host is stubbed so CI never depends on NWS uptime.
const CLOUDGIS_HOSTNAME = 'mapservices.weather.noaa.gov'

// Exact hostname comparison on the parsed URL (a substring test would also match
// look-alike hosts).
function isCloudGisUrl(value) {
  try {
    return new URL(value).hostname === CLOUDGIS_HOSTNAME
  } catch {
    return false
  }
}

const TRANSPARENT_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
)

test('NWS CloudGIS overlays are opt-in and request tiles only when toggled on', async ({ page }) => {
  const failures = trackRuntimeFailures(page)
  const consoleErrors = []
  page.on('console', (message) => {
    if (message.type() !== 'error') return
    const urls = [message.location()?.url, ...(message.text().match(/https?:\/\/[^\s"')]+/g) ?? [])]
    if (urls.some((url) => url && isCloudGisUrl(url))) consoleErrors.push(message.text())
  })
  const requested = []
  await page.route((url) => url.hostname === CLOUDGIS_HOSTNAME, async (route) => {
    requested.push(route.request().url())
    await route.fulfill({
      status: 200,
      contentType: 'image/png',
      headers: { 'access-control-allow-origin': '*' },
      body: TRANSPARENT_PNG,
    })
  })

  await page.goto('/map', { waitUntil: 'domcontentloaded' })
  const radar = page.getByRole('button', { name: 'NWS radar' })
  await expect(radar).toBeVisible()
  await expect(radar).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByText(/NWS live overlays · display only/)).toBeVisible()
  expect(requested).toEqual([])

  await radar.click()
  await expect(radar).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => requested.some((url) => url.includes('/radar/radar_base_reflectivity/MapServer/export'))).toBe(true)

  const warnings = page.getByRole('button', { name: 'NWS warnings' })
  await warnings.click()
  await expect(warnings).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => requested.some((url) => url.includes('/WWA/watch_warn_adv/MapServer/export'))).toBe(true)
  await expect(page.getByText(/NWS radar: live/)).toBeVisible()
  await expect(page.getByText(/not stored or validated by AguaYLuz/)).toBeVisible()

  expect(consoleErrors, consoleErrors.join('\n')).toEqual([])
  expect(failures, failures.join('\n')).toEqual([])
})
