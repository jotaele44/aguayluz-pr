import fs from 'node:fs/promises'
import { expect, test } from '@playwright/test'

const endpoint = 'http://127.0.0.1:8000/electricity/v1/acquisition-jobs'
async function open(page, operator = true) {
  if (operator) await page.addInitScript(() => sessionStorage.setItem('aguayluz_api_key', 'synthetic-browser-review-role'))
  await page.goto('/electricity')
  await page.getByRole('button', { name: 'Source acquisition', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Durable monthly acquisition jobs' })).toBeVisible()
}
async function create(page, column = 'generation') {
  await page.getByLabel('Source data column', { exact: true }).fill(column)
  await page.getByLabel('First source month').fill('2026-01')
  await page.getByLabel('Last source month').fill('2026-03')
  await page.getByLabel('Rows per page').fill('1')
  const response = page.waitForResponse(r => r.url() === endpoint && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Create acquisition job', exact: true }).click()
  return (await response).json()
}
async function step(card, page) {
  const response = page.waitForResponse(r => r.url().endsWith('/step'))
  await card.getByRole('button', { name: 'Run next step / retry', exact: true }).click()
  return (await response).json()
}

test('native acquisition resumes pages after real adapter failure, exports and replays durable status', async ({ page, request }) => {
  await open(page)
  const created = await create(page)
  const card = page.getByRole('region', { name: created.job_id, exact: true })
  for (let i = 0; i < 3; i++) await step(card, page)
  await expect(card).toContainText('Captured rows: 1')
  const failed = await step(card, page)
  expect(failed.status).toBe('FAILED')
  await expect(card).toContainText('EIA_RETRY_EXHAUSTED')
  await step(card, page)
  const final = await step(card, page)
  expect(final.status).toBe('COMPLETE')
  await expect(card).toContainText('Captured rows: 3')
  await expect(card.getByRole('button', { name: 'Run next step / retry', exact: true })).toBeDisabled()
  const event = page.waitForEvent('download')
  await card.getByRole('button', { name: 'Export job evidence' }).click()
  const download = await event
  const exported = JSON.parse(await fs.readFile(await download.path(), 'utf8'))
  expect(exported.receipt_sha256).toHaveLength(5)
  expect(exported.canonical_promotion).toBe('BLOCKED')
  expect(JSON.stringify(exported)).not.toContain('synthetic-browser-source-key')
  const projection = await (await request.get('http://127.0.0.1:8000/electricity/v1/projection')).json()
  expect(Object.values(projection.states).every(s => s.measurements.length === 0)).toBe(true)
  await page.reload()
  await page.getByRole('button', { name: 'Source acquisition', exact: true }).click()
  await expect(page.getByRole('region', { name: created.job_id, exact: true })).toContainText('Complete (AUDIT ONLY)')
})

test('native cancellation fences an actual in-flight source page', async ({ page, request }) => {
  await open(page)
  const created = await create(page, 'slow_generation')
  const card = page.getByRole('region', { name: created.job_id, exact: true })
  await step(card, page); await step(card, page)
  const response = page.waitForResponse(r => r.url().endsWith('/step'))
  await card.getByRole('button', { name: 'Run next step / retry', exact: true }).click()
  await expect(card.getByRole('status', { name: 'Current job status', exact: true })).toContainText('Running')
  await card.getByRole('button', { name: 'Cancel job', exact: true }).click()
  expect((await response).status()).toBe(409)
  await expect(card).toContainText('Cancelled')
  const actual = await (await request.get(endpoint + '/' + created.job_id)).json()
  expect(actual.rows).toBe(0)
  expect(actual.receipt_sha256).toHaveLength(2)
})

test('native acquisition job creation denies unauthorized operators', async ({ page }) => {
  await open(page, false)
  await create(page)
  await expect(page.getByText(/Operation failed: ELECTRICITY_HTTP_401/)).toBeVisible()
})

test('job history integrity failure closes controls and recovers bilingually on mobile', async ({ page }, testInfo) => {
  let failed = true
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/electricity/v1/acquisition-jobs?*', route => failed
    ? route.fulfill({ status: 503, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ detail: 'EIA_JOB_INTEGRITY_OR_STORAGE_FAILED' }) })
    : route.continue())
  await open(page)
  await expect(page.getByRole('alert')).toContainText('Job history is unavailable')
  await expect(page.getByRole('button', { name: 'Create acquisition job', exact: true })).toBeDisabled()
  failed = false
  await page.getByRole('button', { name: 'Refresh job status', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Create acquisition job', exact: true })).toBeEnabled()
  await page.getByLabel('Language').selectOption('es')
  await expect(page.getByLabel('Primer mes de la fuente')).toBeVisible()
  const button = page.getByRole('button', { name: 'Crear trabajo de adquisición', exact: true })
  await button.click({ trial: true })
  await expect(button).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('acquisition-jobs-mobile-es.png') })
})
