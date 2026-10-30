import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getElectricityRegistry, getElectricityRegistryHistory } from '@/lib/electricity-api'
import ElectricityRegistry from './ElectricityRegistry'

vi.mock('@/lib/electricity-api', () => ({ getElectricityRegistry: vi.fn(), getElectricityRegistryHistory: vi.fn() }))
const revision = 'a'.repeat(64)
const entity = () => ({ entity_id: 'b'.repeat(64), source_system: 'EIA-860M', plant_id: '1', generator_id: '01', identity_basis: 'SOURCE_GENERATOR_IDENTIFIER', names: ['Synthetic candidate'], selected_claim_count: 2, history_claim_count: 3, conflicting_pair_count: 1 })
const page = () => ({ source_revision: revision, certification: 'NOT_CERTIFIED', total: 1, next_offset: null, entities: [entity()] })
const detail = () => ({ entity: entity(), next_offset: null, sources: [{ authority: 'Synthetic fixture', license: 'UNRESOLVED', published_at: null, retrieved_at: '2026-01-01T00:00:00Z', source_url: 'https://www.eia.gov/', sha256: 'c'.repeat(64) }], claims: [{ claim_id: 'd'.repeat(64), selected_at: true, conflicting_claim_ids: ['e'.repeat(64)], claim: { name: 'Synthetic candidate', valid_from: '2026-01-01T00:00:00Z', valid_to: null, nameplate_mw: 1, status: 'OP', review_state: 'AUDIT_ONLY', receipt_sha256: 'c'.repeat(64) } }] })
function mount(locale = 'en') {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ElectricityRegistry locale={locale} sourceRevision={revision} /></QueryClientProvider>)
}
describe('temporal source registry', () => {
  beforeEach(() => { vi.resetAllMocks(); getElectricityRegistry.mockResolvedValue(page()); getElectricityRegistryHistory.mockResolvedValue(detail()) })
  it('shows literal identity, conflicting counts and complete source disclosures', async () => {
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Inspect history: EIA-860M 1 / 01' }))
    const history = await screen.findByRole('table', { name: 'Source assertion history' })
    expect(history).toHaveTextContent('Open end')
    expect(history).toHaveTextContent('AUDIT_ONLY')
    expect(history).toHaveTextContent('e'.repeat(64))
    expect(getElectricityRegistryHistory).toHaveBeenCalledWith('b'.repeat(64), { offset: 0, limit: 20, revision })
    fireEvent.click(screen.getByText('Source disclosures for this history page'))
    expect(await screen.findByText('Synthetic fixture')).toBeVisible()
    expect(screen.getByRole('note')).toHaveTextContent('not operating state')
  })
  it('applies literal filters and UTC instant without scientific writes', async () => {
    mount()
    await screen.findByText('Synthetic candidate')
    fireEvent.change(screen.getByLabelText('Entity type'), { target: { value: 'plant' } })
    fireEvent.change(screen.getByLabelText('Source system'), { target: { value: 'EIA-860' } })
    fireEvent.change(screen.getByLabelText('Exact plant ID'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Literal name or ID contains'), { target: { value: '01' } })
    fireEvent.change(screen.getByLabelText('Effective instant (UTC)'), { target: { value: '2026-01-01T00:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply registry filters' }))
    await waitFor(() => expect(getElectricityRegistry).toHaveBeenLastCalledWith({ entity_kind: 'plant', source_system: 'EIA-860', plant_id: '1', search: '01', at: '2026-01-01T00:00Z', offset: 0, limit: 20, revision }))
    fireEvent.click(screen.getByRole('button', { name: 'Clear registry filters' }))
    await waitFor(() => expect(getElectricityRegistry).toHaveBeenLastCalledWith({ entity_kind: 'generator', offset: 0, limit: 20, revision }))
  })
  it('pins list and history continuation pages and returns safely', async () => {
    getElectricityRegistry.mockResolvedValueOnce({ ...page(), total: 21, next_offset: 20 }).mockResolvedValue({ ...page(), total: 21 })
    getElectricityRegistryHistory.mockResolvedValueOnce({ ...detail(), next_offset: 20 }).mockResolvedValue(detail())
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Next identities' }))
    await waitFor(() => expect(getElectricityRegistry).toHaveBeenLastCalledWith({ entity_kind: 'generator', offset: 20, limit: 20, revision }))
    fireEvent.click(await screen.findByRole('button', { name: 'Inspect history: EIA-860M 1 / 01' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Next history page' }))
    await waitFor(() => expect(getElectricityRegistryHistory).toHaveBeenLastCalledWith('b'.repeat(64), { offset: 20, limit: 20, revision }))
    fireEvent.click(screen.getByRole('button', { name: 'Close history' }))
    expect(screen.queryByRole('region', { name: 'Source assertion history' })).not.toBeInTheDocument()
  })
  it('closes exports on source failure and retries the actual read', async () => {
    getElectricityRegistry.mockRejectedValueOnce(new Error('ELECTRICITY_HTTP_409'))
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent('revision changed')
    expect(screen.queryByRole('button', { name: 'Export this registry page' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh registry evidence' }))
    expect(await screen.findByText('Synthetic candidate')).toBeVisible()
  })
  it('keeps failed detail evidence hidden and recoverable', async () => {
    getElectricityRegistryHistory.mockRejectedValueOnce(new Error('ELECTRICITY_HTTP_503'))
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Inspect history: EIA-860M 1 / 01' }))
    await screen.findByRole('alert')
    expect(screen.queryByRole('button', { name: 'Export this history page' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh registry evidence' }))
    expect(await screen.findByRole('table', { name: 'Source assertion history' })).toBeVisible()
  })
  it('displays genuine empty results as unavailable', async () => {
    getElectricityRegistry.mockResolvedValue({ ...page(), total: 0, entities: [] })
    mount()
    expect(await screen.findByText(/no source assertions match/)).toBeVisible()
    expect(screen.queryByRole('button', { name: /Inspect history:/ })).not.toBeInTheDocument()
  })
  it.each(['en', 'es'])('has accessible registry and source history in %s', async locale => {
    const { container } = mount(locale)
    const inspect = locale === 'en' ? 'Inspect history: EIA-860M 1 / 01' : 'Inspeccionar historial: EIA-860M 1 / 01'
    fireEvent.click(await screen.findByRole('button', { name: inspect }))
    const region = await screen.findByRole('region', { name: locale === 'en' ? 'Source assertion history' : 'Historial de afirmaciones de la fuente' })
    await within(region).findByRole('table')
    expect(within(region).getByRole('region')).toHaveAttribute('tabindex', '0')
    expect((await axe(container)).violations).toEqual([])
  })
})
