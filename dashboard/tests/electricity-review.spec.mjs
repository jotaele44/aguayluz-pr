import fs from 'node:fs/promises'
import { expect, test } from '@playwright/test'

const endpoint = 'http://127.0.0.1:8000/electricity/v1/'
const authorization = { Authorization: 'Bearer synthetic-browser-review-role' }
const science = projection => Object.fromEntries(Object.entries(projection).filter(([key]) => key !== 'generated_at'))

test('authorized native review, reversal, export and bilingual mobile replay preserve source truth', async ({ page, request }, testInfo) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const before = await (await request.get(endpoint + 'projection')).json()
  expect(before.sources[0].authority).toBe('SYNTHETIC BROWSER FIXTURE')
  expect(Object.values(before.states).every(state => state.measurements.length === 0)).toBe(true)
  await page.addInitScript(() => sessionStorage.setItem('aguayluz_api_key', 'synthetic-browser-review-role'))
  await page.goto('/electricity')
  await page.getByRole('button', { name: 'Evidence inspector', exact: true }).click()
  await expect(page.getByLabel('Exact generator claim')).toBeVisible()
  await page.getByLabel('Recommendation', { exact: true }).selectOption('RECOMMEND_EXCLUDE')
  await page.getByLabel('Reason', { exact: true }).selectOption('CAPACITY_CONFLICT')
  await page.getByRole('button', { name: 'Record recommendation' }).click()
  await expect(page.getByText(/Recommendation recorded/)).toBeVisible()
  await expect(page.getByRole('table', { name: 'Immutable review history' }).getByRole('row')).toHaveCount(2)
  let result = await (await request.get(endpoint + 'reviews')).json()
  expect(result.events[0].action).toBe('RECOMMEND_EXCLUDE')
  expect(result.events[0].actor).toBe('SHARED_OPERATOR_KEY')
  expect(result.canonical_promotion).toBe('BLOCKED')
  await page.getByLabel('Recommendation', { exact: true }).selectOption('REVERSE')
  await page.getByLabel('Reason', { exact: true }).selectOption('REVIEW_CORRECTION')
  await page.getByRole('button', { name: 'Record recommendation' }).click()
  await expect(page.getByRole('table', { name: 'Immutable review history' }).getByRole('row')).toHaveCount(3)
  result = await (await request.get(endpoint + 'reviews')).json()
  expect(result.events[1].reverses).toBe(result.events[0].event_id)
  expect(result.claims.every(claim => claim.active_action === null)).toBe(true)
  expect(science(await (await request.get(endpoint + 'projection')).json())).toEqual(science(before))
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export review history JSON' }).click()
  const artifact = await download
  expect(artifact.suggestedFilename()).toBe(`aguayluz-electricity-reviews-${result.revision}.json`)
  expect(JSON.parse(await fs.readFile(await artifact.path(), 'utf8'))).toEqual(result)
  await page.reload()
  await page.getByRole('button', { name: 'Evidence inspector', exact: true }).click()
  await expect(page.getByRole('table', { name: 'Immutable review history' }).getByRole('row')).toHaveCount(3)
  await page.getByRole('region', { name: 'Candidate review recommendations', exact: true }).screenshot({ path: testInfo.outputPath('candidate-review-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Collapse sidebar', exact: true }).click()
  await page.getByLabel('Language').selectOption('es')
  await expect(page.getByLabel('Afirmación exacta del generador')).toBeVisible()
  await page.getByLabel('Recomendación', { exact: true }).selectOption('DEFER')
  const mobileSubmit = page.getByRole('button', { name: 'Registrar recomendación', exact: true })
  await mobileSubmit.click({ trial: true })
  await expect(mobileSubmit).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('region', { name: 'Recomendaciones de revisión de candidatos', exact: true }).screenshot({ path: testInfo.outputPath('candidate-review-mobile-es.png') })
  expect(errors).toEqual([])
})

test('native review requires the configured operator role and retains the history on denial', async ({ page, request }) => {
  const before = await (await request.get(endpoint + 'reviews')).json()
  await page.goto('/electricity')
  await page.getByRole('button', { name: 'Evidence inspector', exact: true }).click()
  await page.getByRole('button', { name: 'Record recommendation' }).click()
  await expect(page.getByText(/Recommendation failed. ELECTRICITY_HTTP_401/)).toBeVisible()
  expect(await (await request.get(endpoint + 'reviews')).json()).toEqual(before)
})

test('concurrent actual operator edits are refused through the GUI and refreshed', async ({ page, request }) => {
  await page.addInitScript(() => sessionStorage.setItem('aguayluz_api_key', 'synthetic-browser-review-role'))
  await page.goto('/electricity')
  await page.getByRole('button', { name: 'Evidence inspector', exact: true }).click()
  await expect(page.getByLabel('Exact generator claim')).toBeVisible()
  const state = await (await request.get(endpoint + 'reviews')).json()
  const intervening = await request.post(endpoint + 'reviews', { headers: authorization, data: {
    request_id: crypto.randomUUID().replaceAll('-', ''), source_revision: state.source_revision,
    expected_review_revision: state.revision, claim_id: state.claims[0].claim_id,
    action: 'DEFER', reason_code: 'ORIGINAL_REQUIRED', reverses: null,
  } })
  expect(intervening.status()).toBe(200)
  await page.getByRole('button', { name: 'Record recommendation' }).click()
  await expect(page.getByText(/History was refreshed/)).toBeVisible()
  const current = await (await request.get(endpoint + 'reviews')).json()
  expect(current.events.length).toBe(state.events.length + 1)
  await expect(page.getByRole('table', { name: 'Immutable review history' }).getByRole('row')).toHaveCount(current.events.length + 1)
})

test('review integrity failure closes export and recovers using the actual producer', async ({ page }) => {
  let failed = true
  await page.route('**/electricity/v1/reviews', route => failed
    ? route.fulfill({ status: 503, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ detail: 'ELECTRICITY_REVIEW_INTEGRITY_FAILED' }) })
    : route.continue())
  await page.goto('/electricity')
  await page.getByRole('button', { name: 'Evidence inspector', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Review history is unavailable')
  await expect(page.getByRole('button', { name: 'Export review history JSON' })).toBeDisabled()
  failed = false
  await page.getByRole('button', { name: 'Refresh review history' }).click()
  await expect(page.getByLabel('Exact generator claim')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Export review history JSON' })).toBeEnabled()
})
