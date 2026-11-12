import { expect, test } from '@playwright/test'

const backendUrl = 'http://127.0.0.1:8000'
const CLASS_ORDER = ['above_optimum', 'optimum', 'observation', 'operational_adjustment', 'critical']

function trackRuntimeFailures(page) {
  const failures = []
  page.on('pageerror', (error) => failures.push(`page error: ${error.message}`))
  page.on('response', (response) => {
    if (response.status() >= 500) failures.push(`${response.status()} ${response.url()}`)
  })
  return failures
}

test('Aquifer Bands is reachable from the sidebar and shows the wells, their bands and provenance', async ({ page, request }) => {
  const failures = trackRuntimeFailures(page)

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const link = page.locator('a[href="/aquifer-bands"]').first()
  await expect(link, 'No clickable GUI navigation reaches /aquifer-bands').toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/aquifer-bands\/?$/)

  await expect(page.getByRole('heading', { name: 'Aquifer Bands' })).toBeVisible()
  await expect(page.getByRole('note', { name: 'Aquifer bands scope' })).toContainText(/not an alert/i)

  const table = page.getByRole('table', { name: 'Aquifer observation wells' })
  await expect(table).toBeVisible()
  await expect(table.locator('tbody tr')).toHaveCount(5)

  const source = page.getByTestId('aquifer-source')
  await expect(source).toBeVisible()
  await expect(source.getByText(/^(FRESH|STALE|FAILED|NEVER)$/)).toBeVisible()

  // The API behind the page: the contract the panel renders.
  const body = await (await request.get(`${backendUrl}/aquifer/bands`)).json()
  expect(body.scope.completeness_claimed).toBe(false)
  expect(body.scope.alerting).toBe('display_only')
  expect(body.scope.evidence_tier).toBe('T2')
  expect(body.scope.effective_date).toBeNull()
  expect(body.items).toHaveLength(5)
  for (const item of body.items) {
    expect(item.asset_id).toBe(`USGSGW_${item.site_no}`)
    expect(item.bands.map((band) => band.class)).toEqual(CLASS_ORDER)
    expect(item.bands[0].shallow_ft).toBe(0)
    item.bands.slice(1).forEach((band, i) => expect(band.shallow_ft).toBe(item.bands[i].deep_ft))
    expect(item.critical_onset_ft).toBe(item.bands[4].shallow_ft)
    expect(item.source_byte_sha256).toMatch(/^[0-9a-f]{64}$/)
    // A class is only ever claimed from a reading.
    expect(item.class === null).toBe(item.reading === null)
  }
  expect(body.source.receipt.last_success.byte_sha256).toMatch(/^[0-9a-f]{64}$/)

  // CI has no readings files: the wells must still render, and say plainly that no condition is claimed.
  if (body.counts.with_reading === 0) {
    await expect(page.getByText(/No current reading, so no condition is claimed/)).toHaveCount(5)
  } else {
    expect(body.counts.critical).toBe(body.items.filter((item) => item.class === 'critical').length)
  }

  expect(failures, failures.join('\n')).toEqual([])
})

test('every well\'s band edges can be opened and name all five classes', async ({ page }) => {
  const failures = trackRuntimeFailures(page)
  await page.goto('/aquifer-bands', { waitUntil: 'domcontentloaded' })
  const table = page.getByRole('table', { name: 'Aquifer observation wells' })
  await expect(table).toBeVisible()

  const first = table.locator('tbody tr').first()
  await first.getByText('Band edges').click()
  const edges = first.locator('details li')
  await expect(edges).toHaveCount(5)
  await expect(edges.last()).toContainText(/^Critical:/)

  // Each bar has a text alternative, so the bands are not conveyed by colour alone.
  await expect(first.getByRole('img')).toHaveAccessibleName(/Bands, in feet below land surface/)
  expect(failures, failures.join('\n')).toEqual([])
})
