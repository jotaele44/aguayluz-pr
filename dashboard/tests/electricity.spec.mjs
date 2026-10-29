import { expect, test } from '@playwright/test'

test('electricity is discoverable and bound to the real read-only producer', async ({ page, request }, testInfo) => {
  const failures = []
  page.on('pageerror', error => failures.push(error.message))
  await page.goto('/')
  await page.getByRole('link', { name: 'Electricity Intelligence' }).click()
  await expect(page).toHaveURL(/\/electricity$/)
  await expect(page.getByRole('heading', { name: 'Electricity Intelligence' })).toBeVisible()
  await expect(page.getByRole('note')).toContainText('Unavailable data do not mean zero')
  const response = await request.get('http://127.0.0.1:8000/electricity/v1/projection')
  expect(response.status()).toBe(200)
  const projection = await response.json()
  expect(projection.certification).toBe('NOT_CERTIFIED')
  expect(projection.jurisdiction).toBe('PR')
  expect(projection.canonical_promotion).toBe('BLOCKED')
  await expect(page.getByText(`NOT_CERTIFIED · revision ${projection.revision}`)).toBeVisible()
  await page.getByRole('button', { name: 'Grid Monitor' }).click()
  await expect(page.getByLabel('Evidence class')).toBeVisible()
  for (const kind of ['OBSERVED', 'RECONSTRUCTED', 'FORECAST', 'SOURCE_CANDIDATE']) {
    await page.getByLabel('Evidence class').selectOption(kind)
    if (!projection.states[kind].measurements.length) await expect(page.getByRole('status', { name: 'Grid Monitor' })).toContainText('Unavailable')
  }
  await page.screenshot({ path: testInfo.outputPath('electricity-desktop.png'), fullPage: true })
  expect(failures).toEqual([])
})

test('electricity keyboard localization, evidence export and mobile layout', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/electricity')
  await expect(page.getByText(/NOT_CERTIFIED · revision/)).toBeVisible()
  const language = page.getByLabel('Language')
  await language.focus()
  await language.selectOption('es')
  await expect(page.getByRole('heading', { name: 'Inteligencia Eléctrica' })).toBeVisible()
  await page.getByRole('button', { name: 'Inspector de evidencia' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Criterios bloqueados' })).toBeVisible()
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Exportar evidencia JSON' }).click()
  expect((await downloaded).suggestedFilename()).toMatch(/^aguayluz-electricity-[0-9a-f]{64}\.json$/)
  await page.getByRole('button', { name: 'Guardar vista' }).click()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Inteligencia Eléctrica' })).toBeVisible()
  await expect(page.getByText(/NOT_CERTIFIED · revision/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('electricity-mobile-es.png'), fullPage: true })
})

test('electricity acquisition denies unauthenticated writes through the GUI', async ({ page }) => {
  await page.goto('/electricity')
  await page.getByRole('button', { name: 'Source acquisition' }).click()
  await page.getByLabel('Official EIA workbook URL').fill('https://www.eia.gov/electricity/data/eia860m/archive/xls/march_generator2026.xlsx')
  await page.getByRole('button', { name: 'Acquire original workbook' }).click()
  await expect(page.getByText(/ELECTRICITY_HTTP_(503|401)/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Acquire original workbook' })).toBeEnabled()
})

test('electricity source integrity failure disables export and recovers through retry', async ({ page }) => {
  // Inject an API integrity failure, then retry the actual producer. No source
  // measurements or successful projection responses are fabricated by this test.
  let fail = true
  await page.route('**/electricity/v1/projection', route => fail
    ? route.fulfill({ status: 503, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ detail: 'ELECTRICITY_EVIDENCE_INTEGRITY_FAILED' }) })
    : route.continue())
  await page.goto('/electricity')
  await expect(page.getByRole('alert')).toContainText('Electricity evidence is unavailable')
  await expect(page.getByRole('button', { name: 'Export evidence JSON' })).toBeDisabled()
  await expect(page.getByText(/NOT_CERTIFIED · revision/)).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: 'Retry' }).click()
  await expect(page.getByText(/NOT_CERTIFIED · revision/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Export evidence JSON' })).toBeEnabled()
})
