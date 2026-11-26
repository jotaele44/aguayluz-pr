import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cancelElectricityJob, createElectricityJob, getElectricityJobs, stepElectricityJob } from '@/lib/electricity-api'
import ElectricityJobs from './ElectricityJobs'

vi.mock('@/lib/electricity-api', () => ({ cancelElectricityJob: vi.fn(), createElectricityJob: vi.fn(), getElectricityJobs: vi.fn(), stepElectricityJob: vi.fn() }))
const job = () => ({ job_id: 'a'.repeat(32), version: 5, status: 'QUEUED', phase: 'PAGES', spec: { endpoint: 'facility-fuel', data_column: 'generation', start: '2026-01', end: '2026-03' }, rows: 1, total: 3, error: null, can_step: true, can_cancel: true, receipt_sha256: ['b'.repeat(64)], history: [] })
const listing = jobs => ({ jobs, total: jobs.length, next_offset: null })
function mount(locale = 'en') {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ElectricityJobs locale={locale} /></QueryClientProvider>)
}
function dates() {
  fireEvent.change(screen.getByLabelText('First source month'), { target: { value: '2026-01' } })
  fireEvent.change(screen.getByLabelText('Last source month'), { target: { value: '2026-03' } })
}

describe('durable source acquisition controls', () => {
  beforeEach(() => { vi.clearAllMocks(); getElectricityJobs.mockResolvedValue(listing([job()])) })
  it('binds creation and retries to one unchanged request identity', async () => {
    createElectricityJob.mockRejectedValueOnce(new Error('network unavailable')).mockResolvedValueOnce({ ...job(), status: 'QUEUED' })
    mount()
    await screen.findByRole('button', { name: 'Run next step / retry' })
    dates()
    fireEvent.click(screen.getByRole('button', { name: 'Create acquisition job' }))
    await screen.findByText(/Operation failed/)
    fireEvent.click(screen.getByRole('button', { name: 'Create acquisition job' }))
    await screen.findByText(/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa: Queued/)
    expect(createElectricityJob.mock.calls[0][0]).toEqual(createElectricityJob.mock.calls[1][0])
    expect(createElectricityJob.mock.calls[0][0]).toMatchObject({ endpoint: 'facility-fuel', state_facet: 'state', start: '2026-01', end: '2026-03', page_size: 1000 })
  })

  it('keeps failed partial pages distinct from a completed acquisition', async () => {
    const failed = { ...job(), status: 'FAILED', error: 'EIA_RETRY_EXHAUSTED' }
    stepElectricityJob.mockResolvedValue(failed)
    getElectricityJobs.mockResolvedValueOnce(listing([job()])).mockResolvedValue(listing([failed]))
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Run next step / retry' }))
    await screen.findByText(/Failed: EIA_RETRY_EXHAUSTED/)
    expect(stepElectricityJob).toHaveBeenCalledWith('a'.repeat(32), 5)
    expect(screen.getByText('Captured rows: 1 · Source total: 3')).toBeVisible()
    expect(screen.queryByText('Complete (AUDIT ONLY)')).not.toBeInTheDocument()
  })

  it('permits cancellation while the source step is pending', async () => {
    let finish
    stepElectricityJob.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    cancelElectricityJob.mockResolvedValue({ ...job(), status: 'CANCELLED' })
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Run next step / retry' }))
    expect(screen.getByRole('button', { name: 'Cancel job' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }))
    await waitFor(() => expect(cancelElectricityJob).toHaveBeenCalledWith('a'.repeat(32), 5))
    finish(job())
  })

  it('refreshes conflicting versions without automatically repeating the mutation', async () => {
    stepElectricityJob.mockRejectedValue(new Error('ELECTRICITY_HTTP_409'))
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Run next step / retry' }))
    await screen.findByText(/Job changed or another worker/)
    expect(stepElectricityJob).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(getElectricityJobs).toHaveBeenCalledTimes(2))
  })

  it('fails closed on unavailable history and supports an actual refresh', async () => {
    getElectricityJobs.mockRejectedValueOnce(new Error('ELECTRICITY_HTTP_503'))
    mount()
    await screen.findByRole('alert')
    expect(screen.getByRole('button', { name: 'Create acquisition job' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh job status' }))
    await screen.findByRole('button', { name: 'Run next step / retry' })
    expect(screen.getByRole('button', { name: 'Create acquisition job' })).toBeEnabled()
  })

  it('requests older pages through the read-only API rather than hiding jobs', async () => {
    getElectricityJobs.mockResolvedValueOnce({ jobs: [job()], total: 21, next_offset: 20 }).mockResolvedValue(listing([]))
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Next jobs' }))
    await waitFor(() => expect(getElectricityJobs).toHaveBeenCalledWith(20))
  })

  it.each(['en', 'es'])('provides accessible complete controls in %s', async locale => {
    const { container } = mount(locale)
    await screen.findByRole('button', { name: locale === 'en' ? 'Run next step / retry' : 'Ejecutar próximo paso / reintentar' })
    expect((await axe(container)).violations).toEqual([])
  })
})
