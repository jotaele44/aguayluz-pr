import { expect, test } from '@playwright/test'

const backendUrl = 'http://127.0.0.1:8000'

test('food resilience is discoverable, read-only, and phase guarded', async ({ page, request }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const link = page.locator('a[href="/food-resilience"]').first()
  await expect(link).toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/food-resilience\/?$/)
  await expect(page.getByRole('heading', { name: 'Food System Resilience' })).toBeVisible()
  await expect(page.getByText('Scientific model → canonical state → deterministic GUI projection')).toBeVisible()
  await expect(page.getByText('Phase 1 — observable warning indicators')).toBeVisible()
  await expect(page.getByText('Phase 2 — Vector A baseline ledger')).toBeVisible()
  await expect(page.getByText('Dynamic scenario estimates')).toBeVisible()
  await expect(page.getByText('Robust food-resilience monitoring')).toBeVisible()
  await expect(page.getByText('MODEL_UNAVAILABLE').first()).toBeVisible()

  const stateResponse = await request.get(`${backendUrl}/food-resilience/state`)
  expect(stateResponse.status()).toBe(200)
  const state = await stateResponse.json()
  expect(state.vector_id).toBe('FOOD_SYSTEM_RESILIENCE')
  expect(state.activation_phase).toBe(1)
  expect(state.metrics.dynamic_coverage.value).toBeNull()
  expect(state.metrics.dynamic_coverage.availability_state).toBe('MODEL_UNAVAILABLE')
  expect(state.metrics.robust_coverage_p50.value).toBeNull()
  expect(state.metrics.robust_coverage_p50.availability_state).toBe('MODEL_UNAVAILABLE')

  const baselineResponse = await request.get(`${backendUrl}/food-resilience/baseline`)
  expect(baselineResponse.status()).toBe(200)
  const baseline = await baselineResponse.json()
  expect(baseline.current_operational_baseline).toBe(false)

  expect((await request.post(`${backendUrl}/food-resilience/state`)).status()).toBe(405)
})
