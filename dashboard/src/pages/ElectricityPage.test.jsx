import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElectricityPage from './ElectricityPage'
import { getElectricityProjection, acquireElectricityWorkbook, importElectricityWorkbook } from '@/lib/electricity-api'

vi.mock('@/lib/electricity-api', () => ({ getElectricityProjection: vi.fn(), acquireElectricityWorkbook: vi.fn(), importElectricityWorkbook: vi.fn(), uploadElectricityWorkbook: vi.fn(), getElectricityReviews: vi.fn(), appendElectricityReview: vi.fn() }))

const empty = () => ({
  revision: 'a'.repeat(64), certification: 'NOT_CERTIFIED', generator_claims: [], sources: [], contradictions: [], gaps: ['EIA_LIVE_SCHEMA_UNVERIFIED'],
  states: Object.fromEntries(['OBSERVED', 'RECONSTRUCTED', 'FORECAST', 'SOURCE_CANDIDATE'].map(k => [k, { availability: 'UNAVAILABLE', measurements: [] }])),
})
function mount() {
  return render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ElectricityPage /></QueryClientProvider></MemoryRouter>)
}

describe('native electricity evidence workspace', () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); getElectricityProjection.mockResolvedValue(empty()) })

  it('discloses source limits and unavailable states without fabricated telemetry', async () => {
    mount()
    await screen.findByText(/NOT_CERTIFIED/)
    expect(screen.getByRole('note')).toHaveTextContent(/No authoritative live grid feed/)
    fireEvent.click(screen.getByRole('button', { name: 'Grid Monitor' }))
    expect(screen.getByRole('status', { name: 'Grid Monitor' })).toHaveTextContent(/Unavailable/)
    fireEvent.change(screen.getByLabelText('Evidence class'), { target: { value: 'FORECAST' } })
    expect(screen.getByRole('status', { name: 'Grid Monitor' })).toHaveTextContent(/Unavailable/)
  })

  it('localizes the full workspace controls and saves presentation preferences', async () => {
    mount()
    await screen.findByText(/NOT_CERTIFIED/)
    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'es' } })
    expect(screen.getByRole('heading', { name: 'Inteligencia Eléctrica' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Guardar vista' }))
    expect(JSON.parse(localStorage.getItem('electricity-view-v1'))).toEqual({ locale: 'es', kind: 'OBSERVED' })
    fireEvent.click(screen.getByRole('button', { name: 'Monitor de la red' }))
    expect(screen.getByLabelText('Clase de evidencia')).toBeVisible()
  })

  it('shows acquisition failure and safely retries without claiming source success', async () => {
    acquireElectricityWorkbook.mockRejectedValue(new Error('ELECTRICITY_HTTP_503'))
    mount()
    await screen.findByText(/NOT_CERTIFIED/)
    fireEvent.click(screen.getByRole('button', { name: 'Source acquisition' }))
    fireEvent.change(screen.getByLabelText('Official EIA workbook URL'), { target: { value: 'https://www.eia.gov/electricity/data/eia860m/xls/test.xlsx' } })
    fireEvent.click(screen.getByRole('button', { name: 'Acquire original workbook' }))
    await screen.findByText('ELECTRICITY_HTTP_503')
    expect(screen.getByRole('button', { name: 'Acquire original workbook' })).toBeEnabled()
    expect(acquireElectricityWorkbook).toHaveBeenCalledTimes(1)
  })

  it('imports only a captured hash and explicit worksheet/date, showing accounting', async () => {
    importElectricityWorkbook.mockResolvedValue({ arithmetic: { source: 2, retained: 1, excluded: 1, unresolved: 0 }, canonical_promotion: 'BLOCKED' })
    mount()
    await screen.findByText(/NOT_CERTIFIED/)
    fireEvent.click(screen.getByRole('button', { name: 'Source acquisition' }))
    fireEvent.change(screen.getByLabelText('Captured workbook SHA-256'), { target: { value: 'b'.repeat(64) } })
    fireEvent.change(screen.getByLabelText('Snapshot effective date'), { target: { value: '2026-10-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Import EIA-860M claims' }))
    await waitFor(() => expect(importElectricityWorkbook).toHaveBeenCalledWith({ sha256: 'b'.repeat(64), sheet_path: 'xl/worksheets/sheet1.xml', effective_at: '2026-10-01T00:00:00Z' }))
    await screen.findByText(/"canonical_promotion":"BLOCKED"/)
  })

  it('fails visibly on transport failure and offers a working retry', async () => {
    getElectricityProjection.mockRejectedValueOnce(new Error('offline'))
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent(/evidence is unavailable/)
    expect(screen.getByRole('button', { name: 'Export evidence JSON' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText(/NOT_CERTIFIED/)
  })

  it('has no automated accessibility violations in English and Spanish', async () => {
    const { container } = mount()
    await screen.findByText(/NOT_CERTIFIED/)
    expect((await axe(container)).violations).toEqual([])
    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'es' } })
    fireEvent.click(screen.getByRole('button', { name: 'Adquisición de fuentes' }))
    expect((await axe(container)).violations).toEqual([])
  })
})
