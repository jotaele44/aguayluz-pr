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
