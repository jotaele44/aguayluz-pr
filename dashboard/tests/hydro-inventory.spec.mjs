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

test('Hydro Inventory is reachable from the sidebar and shows coverage, aquifers and wells from committed data', async ({ page, request }) => {
  const failures = trackRuntimeFailures(page)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const link = page.locator('a[href="/hydro-inventory"]').first()
  await expect(link, 'No clickable GUI navigation reaches /hydro-inventory').toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/hydro-inventory\/?$/)
  await expect(page.getByRole('heading', { name: 'Hydro Inventory' })).toBeVisible()

  const body = await (await request.get(`${backendUrl}/hydro/inventory/summary`)).json()
  expect(body.scope.completeness_claimed).toBe(false)
  expect(body.phase_scope.feature_types_not_enumerated).toEqual([])
  expect(body.phase_scope.feature_types_enumerated).toEqual(expect.arrayContaining(['aquifer', 'well', 'spring', 'stream', 'gauge']))
  const { aquifer, well } = body.coverage
  expect(aquifer.features_lower).toBeLessThanOrEqual(aquifer.features_upper)
  for (const ledger of Object.values(body.source_ledgers)) expect(ledger.state).toBe('PASS')

  await expect(page.getByTestId('tile-wells')).toContainText(String(well.features_upper))
  const aquifers = page.getByRole('table', { name: 'Aquifers' })
  await expect(aquifers).toBeVisible()
  await expect(aquifers.locator('tbody tr')).toHaveCount(aquifer.features_upper)

  // CI has no reading files: the page must say that instead of calling every well unmonitored.
  if (!body.monitoring.readings_present) {
    await expect(page.getByText(/property of this server, not of the wells/)).toBeVisible()
  }

  await page.getByRole('button', { name: 'Wells' }).click()
  await expect(page.getByRole('table', { name: 'Wells' }).locator('tbody tr')).toHaveCount(50)
  await page.getByRole('button', { name: 'Conflicts' }).click()
  await expect(page.getByTestId('conflict').first()).toBeVisible()
  expect(failures, failures.join('\n')).toEqual([])
})

test('groundwater series on Monitoring can be filtered by aquifer', async ({ page, request }) => {
  const failures = trackRuntimeFailures(page)
  const wells = await (await request.get(`${backendUrl}/hydro/aquifer-wells?aquifer=AQ:USGS_AQFR:110SCPL`)).json()
  expect(wells.authoritative).toBeGreaterThan(100)
  await page.goto('/monitoring', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: /Groundwater/ }).first().click()
  await page.getByRole('combobox', { name: 'Monitoring series' }).click()
  await page.getByRole('option', { name: 'Groundwater depth (discrete)' }).click()
  const filter = page.getByTestId('aquifer-filter')
  await expect(filter).toBeVisible()
  await filter.getByRole('combobox', { name: 'Aquifer filter' }).click()
  await page.getByRole('option', { name: /South Coastal Plain Alluvial Aquifer/ }).click()
  await expect(filter).toContainText(`${wells.authoritative} assigned by a USGS aquifer code`)
  expect(failures, failures.join('\n')).toEqual([])
})
