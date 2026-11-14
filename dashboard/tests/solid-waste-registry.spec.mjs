import { expect, test } from '@playwright/test'

const backendUrl = 'http://127.0.0.1:8000'
const KINDS = ['LANDFILL', 'SOLID_WASTE_FACILITY', 'DISPOSAL_SITE']

// Data-driven on purpose: no site name or count is hard-coded, so a registry
// refresh does not break this test. What it pins is that the page shows exactly
// what the real API holds and never states a status the source did not.
test('solid-waste site registry lists exactly what the API holds and never invents a status', async ({ page, request }) => {
  const runtimeFailures = []
  page.on('pageerror', (error) => runtimeFailures.push(`page error: ${error.message}`))
  page.on('response', (response) => {
    if (response.status() >= 500) runtimeFailures.push(`${response.status()} ${response.url()}`)
  })

  const records = []
  for (const kind of KINDS) {
    const response = await request.get(`${backendUrl}/environmental-exposure/entities?entity_kind=${kind}&limit=500`)
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body.items.length).toBe(body.total)
    records.push(...body.items)
  }
  // The committed registry is not empty; an empty list here means the fixture, not the page, is wrong.
  expect(records.length).toBeGreaterThan(0)

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const link = page.locator('a[href="/environmental-exposure"]').first()
  await expect(link).toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/environmental-exposure\/?$/)

  const region = page.getByRole('region', { name: 'Solid-waste site registry' })
  await expect(region).toBeVisible()
  await expect(region).toContainText(/not a complete inventory/i)
  await expect(region).toContainText(/nothing about contamination or exposure/i)
  // A list that disagrees with the graph summary renders an alert instead of rows.
  await expect(region.getByRole('alert')).toHaveCount(0)

  const rows = region.locator('tbody tr')
  await expect(rows).toHaveCount(records.length)
  await expect(region).toContainText(`${records.length} records`)

  const needsReview = records.filter((record) => record.review_status === 'needs_review').length
  await expect(region).toContainText(`${needsReview} need review`)

  // Closure column is the 6th cell. It may only say Closed <year>, "No closure recorded"
  // or "Not stated by source": never a bare "Open".
  const closure = await rows.evaluateAll((trs) => trs.map((tr) => tr.cells[5].textContent.trim()))
  for (const text of closure) {
    expect(text).toMatch(/^(Closed \d{4}|No closure recorded|Not stated by source)$/)
  }
  // An ECHO row carries no status, so it must never be given a closure statement.
  const unstated = records.filter((record) => record.authority !== 'EPA_LMOP' && !record.valid_until).length
  expect(closure.filter((text) => text === 'Not stated by source')).toHaveLength(unstated)

  expect(runtimeFailures, runtimeFailures.join('\n')).toEqual([])
})
