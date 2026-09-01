import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import RegulatoryPage from '@/pages/RegulatoryPage'
import {
  getRegulatoryObservation,
  getRegulatoryObservations,
  getRegulatorySummary,
} from '@/lib/regulatory-api'

vi.mock('@/lib/regulatory-api', () => ({
  getRegulatorySummary: vi.fn(),
  getRegulatoryObservations: vi.fn(),
  getRegulatoryObservation: vi.fn(),
  getRegulatoryReceipt: vi.fn(),
}))

const OBSERVATION = {
  observation_id: 'AYL_REGOBS_USGS_001',
  record_family: 'entity',
  provider: 'USGS',
  provider_record_id: '50038100',
  observed_at: '2026-08-19T21:00:00Z',
  retrieved_at: '2026-08-19T21:00:00Z',
  source_receipt_id: 'AYL_REGRCPT_USGS_abc123',
  normalization_version: 'usgs/v1',
  evidence_tier: 'T1',
  freshness_state: 'current',
  identifiers: [{ scheme: 'usgs_site_no', value: '50038100' }],
  payload: { name: 'RIO GRANDE DE ARECIBO AT ARECIBO, PR', site_type_code: 'ST' },
}

const SUMMARY = {
  scope: {
    statement: 'Live provider observations only. An observation is a source\'s own statement, never a claim about which AguaLuz facility it describes.',
  },
  counts: { observations: 1, receipts: 1 },
  provider: { USGS: 1 },
  record_family: { entity: 1 },
  freshness_state: { current: 1 },
  evidence_tier: { T1: 1 },
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <RegulatoryPage />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getRegulatorySummary.mockResolvedValue(SUMMARY)
  getRegulatoryObservations.mockResolvedValue({ total: 1, items: [OBSERVATION] })
  getRegulatoryObservation.mockResolvedValue({
    ...OBSERVATION,
    receipt: {
      receipt_id: OBSERVATION.source_receipt_id,
      retrieved_at: OBSERVATION.retrieved_at,
      retrieval_status: 'success',
      http_status: 200,
      sha256: 'abc123',
      byte_count: 512,
    },
  })
})

describe('RegulatoryPage', () => {
  it('renders the non-authoritative scope note and observation summary', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Regulatory Observations' })).toBeInTheDocument()
    expect(screen.getByRole('note', { name: 'Regulatory framework scope limitation' }))
      .toHaveTextContent(/never a claim/i)
    expect(await screen.findByText(/USGS · 50038100/)).toBeInTheDocument()
  })

  it('selects observations through accessible pressed buttons and loads detail with receipt', async () => {
    renderPage()

    const button = await screen.findByRole('button', { name: /USGS · 50038100/ })
    await waitFor(() => expect(button).toHaveAttribute('aria-pressed', 'true'))
    expect(getRegulatoryObservation).toHaveBeenCalledWith(OBSERVATION.observation_id)
    expect(await screen.findByRole('heading', { name: 'Source receipt' })).toBeInTheDocument()
    expect(await screen.findByText(OBSERVATION.source_receipt_id)).toBeInTheDocument()
  })

  it('shows an empty state when no observations match the filters', async () => {
    getRegulatoryObservations.mockResolvedValue({ total: 0, items: [] })
    renderPage()

    expect(await screen.findByText(/no observations match the current filters/i)).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderPage()
    await screen.findByText(/USGS · 50038100/)
    await screen.findByRole('heading', { name: 'Source receipt' })

    expect(await axe(container)).toHaveNoViolations()
  })
})
