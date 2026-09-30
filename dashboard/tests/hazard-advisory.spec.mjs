import { expect, test } from '@playwright/test'

const backendUrl = 'http://127.0.0.1:8000'

test('hazard advisory plane is reachable through Environmental Exposure and remains fail-closed', async ({ page, request }) => {
  const runtimeFailures = []
  page.on('pageerror', (error) => runtimeFailures.push(`page error: ${error.message}`))
  page.on('response', (response) => {
    if (response.status() >= 500) runtimeFailures.push(`${response.status()} ${response.url()}`)
  })

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const link = page.locator('a[href="/environmental-exposure"]').first()
  await expect(link).toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/environmental-exposure\/?$/)

  await expect(page.getByText('Puerto Rico Hazard & Advisory Plane')).toBeVisible()
  await expect(page.getByRole('note', { name: 'Environmental exposure scope limitation' })).toContainText(/cannot establish.*disease transmission.*cause/i)

  const summaryResponse = await request.get(`${backendUrl}/hazards/summary`)
  expect(summaryResponse.status()).toBe(200)
  const summary = await summaryResponse.json()
  expect(summary.source_universe.completeness_claimed).toBe(false)
  expect(summary.source_universe.certification_state).toBe('OPEN')
  expect(summary.scope.statement).toMatch(/is not causation/i)

  const sourcesResponse = await request.get(`${backendUrl}/hazards/sources`)
  expect(sourcesResponse.status()).toBe(200)
  const sources = await sourcesResponse.json()
  expect(sources.unresolved_material.length).toBeGreaterThan(0)

  const eventsResponse = await request.get(`${backendUrl}/hazards/events?current_only=true`)
  expect(eventsResponse.status()).toBe(200)
  const events = await eventsResponse.json()
  expect(Array.isArray(events.items)).toBe(true)

  expect(runtimeFailures, runtimeFailures.join('\n')).toEqual([])
})
