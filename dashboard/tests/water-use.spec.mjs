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

test('Water Use is reachable from the sidebar and shows the three years, their split and provenance', async ({ page, request }) => {
  const failures = trackRuntimeFailures(page)

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const link = page.locator('a[href="/water-use"]').first()
  await expect(link, 'No clickable GUI navigation reaches /water-use').toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/water-use\/?$/)

  await expect(page.getByRole('heading', { name: 'Water Use' })).toBeVisible()
  await expect(page.getByRole('note', { name: 'Water use scope' })).toContainText(/not measurements of current production/i)

  const table = page.getByRole('table', { name: 'Public-supply withdrawals by source' })
  await expect(table).toBeVisible()
  await expect(table.locator('tbody tr')).toHaveCount(3)
  await expect(page.getByTestId('water-use-year-2020')).toContainText('601.74')
  await expect(page.getByTestId('water-use-year-2020')).toContainText('10.8%')
  // The bar has a text alternative, so the split is not conveyed by colour alone.
  await expect(page.getByTestId('split-bar-2020')).toHaveAccessibleName('2020 public supply: 89.2% surface water, 10.8% groundwater')

  const source = page.getByTestId('water-use-source')
  await expect(source).toBeVisible()
  await expect(source.getByText(/^(PASS|FAIL|NEVER)$/)).toBeVisible()

  // The API behind the page: the contract the panel renders.
  const body = await (await request.get(`${backendUrl}/water-use/estimates`)).json()
  expect(body.scope.completeness_claimed).toBe(false)
  expect(body.scope.alerting).toBe('not_applicable')
  expect(body.scope.unit).toBe('Mgal/d')
  expect(body.years.map((year) => year.year)).toEqual([2010, 2015, 2020])
  for (const year of body.years) {
    const figure = year.categories.public_supply.published
    // Shares are of surface + groundwater, so they are complementary or both absent.
    if (figure.surface_pct !== null) expect(figure.surface_pct + figure.groundwater_pct).toBeCloseTo(100, 1)
    expect(figure.evidence_tier).toBe(figure.extraction_method === 'manual_transcription' ? 'T2' : 'T1')
  }
  expect(body.years[0].categories.public_supply.published.extraction_method).toBe('manual_transcription')
  expect(body.municipios.public_supply['2020']).toHaveLength(78)
  for (const entry of body.source.sources) expect(entry.sha256).toMatch(/^[0-9a-f]{64}$/)
  // A restated figure is reported with no explanation, because the source gives none.
  for (const item of body.restatements) expect(item.explanation).toBeNull()

  expect(failures, failures.join('\n')).toEqual([])
})

test('the municipality table switches year and Water Use links to Aquifer Bands and back', async ({ page }) => {
  const failures = trackRuntimeFailures(page)
  await page.goto('/water-use', { waitUntil: 'domcontentloaded' })

  await expect(page.getByRole('table', { name: 'Public-supply withdrawals by municipality, 2020' })).toBeVisible()
  await page.getByRole('button', { name: '2015' }).click()
  const older = page.getByRole('table', { name: 'Public-supply withdrawals by municipality, 2015' })
  await expect(older).toBeVisible()
  await expect(older.locator('tbody tr')).toHaveCount(78)

  await page.getByRole('note', { name: 'Water use scope' }).getByRole('link', { name: 'Aquifer Bands' }).click()
  await expect(page).toHaveURL(/\/aquifer-bands\/?$/)
  await page.getByRole('note', { name: 'Aquifer bands scope' }).getByRole('link', { name: 'Water Use' }).click()
  await expect(page).toHaveURL(/\/water-use\/?$/)
  expect(failures, failures.join('\n')).toEqual([])
})
