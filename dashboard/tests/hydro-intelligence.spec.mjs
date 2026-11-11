import { expect, test } from '@playwright/test'

test('hydro source readiness is navigable, provenance aware and fail closed', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const link = page.locator('a[href="/hydro-intelligence"]').first()
  await expect(link).toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/hydro-intelligence\/?$/)
  await expect(page.getByRole('heading', { name: 'Hydroelectric Intelligence' })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: /Certification: WITHHELD/ })).toBeVisible()
  const table = page.getByRole('table', { name: 'Hydroelectric evidence sources' })
  await expect(table).toBeVisible()
  await expect(table.locator('tbody tr')).toHaveCount(5)
  await expect(table.getByText('NOT FROZEN').first()).toBeVisible()
})
