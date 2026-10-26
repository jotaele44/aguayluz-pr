import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { appendElectricityReview, getElectricityReviews } from '@/lib/electricity-api'
import ElectricityReviews from './ElectricityReviews'

vi.mock('@/lib/electricity-api', () => ({ appendElectricityReview: vi.fn(), getElectricityReviews: vi.fn() }))
const sourceRevision = 'a'.repeat(64)
const fixture = () => ({
  revision: '0'.repeat(64), source_revision: sourceRevision, events: [],
  claims: [{ claim_id: 'b'.repeat(64), source_identity: 'EIA-860M:1:01', receipt_sha256: 'c'.repeat(64), active_action: null, active_recommendation: null }],
})
function mount(locale = 'en') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><ElectricityReviews locale={locale} sourceRevision={sourceRevision} /></QueryClientProvider>)
}

describe('candidate review workflow', () => {
  beforeEach(() => { vi.clearAllMocks(); getElectricityReviews.mockResolvedValue(fixture()) })

  it('binds recommendations to the exact claim and source/review revisions', async () => {
    appendElectricityReview.mockResolvedValue({ event: { event_id: 'd'.repeat(64) } })
    mount()
    await screen.findByLabelText('Exact generator claim')
    fireEvent.change(screen.getByLabelText('Recommendation'), { target: { value: 'RECOMMEND_EXCLUDE' } })
    fireEvent.click(screen.getByRole('button', { name: 'Record recommendation' }))
    await screen.findByText(/Recommendation recorded/)
    expect(appendElectricityReview).toHaveBeenCalledWith({ request_id: expect.stringMatching(/^[0-9a-f]{32}$/), source_revision: sourceRevision, expected_review_revision: '0'.repeat(64), claim_id: 'b'.repeat(64), action: 'RECOMMEND_EXCLUDE', reason_code: 'ORIGINAL_REQUIRED', reverses: null })
    expect(screen.getByText(/do not certify, promote, exclude or alter scientific evidence/)).toBeVisible()
  })

  it('uses the same idempotency key and body after an uncertain network failure', async () => {
    appendElectricityReview.mockRejectedValueOnce(new Error('network unavailable')).mockResolvedValueOnce({ event: { event_id: 'd'.repeat(64) } })
    mount()
    await screen.findByLabelText('Exact generator claim')
    fireEvent.click(screen.getByRole('button', { name: 'Record recommendation' }))
    await screen.findByText(/Recommendation failed/)
    fireEvent.click(screen.getByRole('button', { name: 'Record recommendation' }))
    await screen.findByText(/Recommendation recorded/)
    expect(appendElectricityReview.mock.calls[0][0]).toEqual(appendElectricityReview.mock.calls[1][0])
  })

  it('refreshes a conflicting history before preparing a new recommendation', async () => {
    getElectricityReviews.mockResolvedValueOnce(fixture()).mockResolvedValue({ ...fixture(), revision: 'e'.repeat(64) })
    appendElectricityReview.mockRejectedValueOnce(new Error('ELECTRICITY_HTTP_409')).mockResolvedValueOnce({ event: { event_id: 'd'.repeat(64) } })
    mount()
    await screen.findByLabelText('Exact generator claim')
    fireEvent.click(screen.getByRole('button', { name: 'Record recommendation' }))
    await screen.findByText(/History was refreshed/)
    await waitFor(() => expect(getElectricityReviews).toHaveBeenCalledTimes(2))
    fireEvent.click(screen.getByRole('button', { name: 'Record recommendation' }))
    await screen.findByText(/Recommendation recorded/)
    expect(appendElectricityReview.mock.calls[1][0].expected_review_revision).toBe('e'.repeat(64))
    expect(appendElectricityReview.mock.calls[1][0].request_id).not.toBe(appendElectricityReview.mock.calls[0][0].request_id)
  })

  it('reverses only the selected active recommendation', async () => {
    const data = fixture()
    data.claims[0].active_recommendation = 'f'.repeat(64)
    data.claims[0].active_action = 'DEFER'
    getElectricityReviews.mockResolvedValue(data)
    appendElectricityReview.mockResolvedValue({ event: { event_id: 'd'.repeat(64) } })
    mount()
    await screen.findByLabelText('Exact generator claim')
    fireEvent.change(screen.getByLabelText('Recommendation'), { target: { value: 'REVERSE' } })
    fireEvent.click(screen.getByRole('button', { name: 'Record recommendation' }))
    await screen.findByText(/Recommendation recorded/)
    expect(appendElectricityReview.mock.calls[0][0].reverses).toBe('f'.repeat(64))
  })

  it('disables writes for empty claims and incoherent scientific revisions', async () => {
    getElectricityReviews.mockResolvedValue({ ...fixture(), claims: [] })
    const view = mount()
    await screen.findByText(/No captured generator claims/)
    expect(screen.getByRole('button', { name: 'Record recommendation' })).toBeDisabled()
    view.unmount()
    getElectricityReviews.mockResolvedValue({ ...fixture(), source_revision: 'f'.repeat(64) })
    mount()
    await screen.findByRole('alert')
    expect(screen.getByRole('button', { name: 'Record recommendation' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Export review history JSON' })).toBeDisabled()
    expect(appendElectricityReview).not.toHaveBeenCalled()
  })

  it('fails closed on review transport/integrity failure and provides retry', async () => {
    getElectricityReviews.mockRejectedValueOnce(new Error('ELECTRICITY_HTTP_503'))
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent(/Writes and review export are disabled/)
    expect(screen.getByRole('button', { name: 'Export review history JSON' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh review history' }))
    await screen.findByLabelText('Exact generator claim')
    expect(screen.getByRole('button', { name: 'Record recommendation' })).toBeEnabled()
  })

  it('keeps authentication failure visible without claiming review success', async () => {
    appendElectricityReview.mockRejectedValue(new Error('ELECTRICITY_HTTP_401'))
    mount()
    await screen.findByLabelText('Exact generator claim')
    fireEvent.click(screen.getByRole('button', { name: 'Record recommendation' }))
    await screen.findByText(/Recommendation failed. ELECTRICITY_HTTP_401/)
    expect(screen.queryByText(/Recommendation recorded/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Record recommendation' })).toBeEnabled()
  })

  it.each(['en', 'es'])('provides accessible review controls in %s', async locale => {
    const { container } = mount(locale)
    await screen.findByLabelText(locale === 'es' ? 'Afirmación exacta del generador' : 'Exact generator claim')
    expect((await axe(container)).violations).toEqual([])
    if (locale === 'es') expect(screen.getByLabelText('Afirmación exacta del generador')).toBeVisible()
  })
})
