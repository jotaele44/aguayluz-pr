import { expect, test } from '@playwright/test'

const preview = process.env.VITE_IONOSPHERE_PREVIEW === '1'
test('ionosphere preview obeys visibility and backend gates', async ({ page, request }) => {
  await page.goto('/')
  const link = page.locator('a[href="/ionosphere"]').first()
  const response = await request.get('http://127.0.0.1:8000/ionosphere/status')
  if (!preview) {
    await expect(page.locator('a[href="/ionosphere"]')).toHaveCount(0)
    expect(response.status()).toBe(404)
    await page.goto('/ionosphere')
    await expect(page.getByRole('heading', { name: 'Space weather / Clima espacial' })).toHaveCount(0)
    return
  }
  await expect(link).toBeVisible()
  await link.click()
  await expect(page.getByRole('heading', { name: 'Space weather / Clima espacial' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Ionosphere source audit' })).toContainText('UNRESOLVED')
  await expect(page.getByRole('note')).toContainText('No confirmed grid damage')
  const payload = await response.json()
  expect(payload.state).toBe('BLOCKED')
  expect(payload.measurements).toBeNull()
  await page.route('**/ionosphere/status', route => route.fulfill({ status: 503, body: '{}' }))
  await page.getByRole('button', { name: 'Retry / Reintentar' }).click()
  await expect(page.getByRole('alert')).toContainText('HTTP 503')
})
