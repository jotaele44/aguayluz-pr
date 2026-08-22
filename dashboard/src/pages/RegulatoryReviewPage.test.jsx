import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import RegulatoryReviewPage from '@/pages/RegulatoryReviewPage'
import {
  getRegulatoryLink,
  getRegulatoryLinks,
  postRegulatoryLinkDecision,
} from '@/lib/regulatory-api'

vi.mock('@/lib/regulatory-api', () => ({
  getRegulatoryLinks: vi.fn(),
  getRegulatoryLink: vi.fn(),
  postRegulatoryLinkDecision: vi.fn(),
}))

const CLEAN_CANDIDATE = {
  candidate_id: 'AYL_REGLINK_USGS_clean001',
  observation_id: 'AYL_REGOBS_USGS_001',
  candidate_asset_id: 'USGS_50038100',
  decision_state: 'proposed',
  match_strength: 'hard_identifier',
  match_features: [{ feature: 'provider_identifier', value: 'usgs_site_no:50038100', source_observation_id: 'AYL_REGOBS_USGS_001' }],
  contradictions: [],
  created_at: '2026-08-19T21:00:00Z',
}

const CONFLICTING_CANDIDATE = {
  ...CLEAN_CANDIDATE,
  candidate_id: 'AYL_REGLINK_USGS_conflict001',
  decision_state: 'needs_review',
  contradictions: [{ kind: 'municipality', detail: 'Observation reports Ponce; asset is in Arecibo.' }],
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <RegulatoryReviewPage />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getRegulatoryLinks.mockResolvedValue({ total: 1, items: [CLEAN_CANDIDATE] })
  getRegulatoryLink.mockResolvedValue({
    ...CLEAN_CANDIDATE,
    observation: { provider: 'USGS', provider_record_id: '50038100' },
  })
})

describe('RegulatoryReviewPage', () => {
  it('renders the fail-closed note and candidate queue', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Regulatory Link Review' })).toBeInTheDocument()
    expect(screen.getByRole('note', { name: 'Adjudication scope limitation' })).toHaveTextContent(/fail-closed/i)
    expect(await screen.findByText('USGS_50038100')).toBeInTheDocument()
  })

  it('disables submit until actor and rationale are filled, then approves a clean candidate', async () => {
    renderPage()

    await screen.findByRole('heading', { name: 'Record a decision' })
    const approveButton = screen.getByRole('button', { name: /approve/i })
    expect(approveButton).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Actor'), { target: { value: 'operator-1' } })
    fireEvent.change(screen.getByLabelText('Rationale'), { target: { value: 'Confirmed exact site number match.' } })
    await waitFor(() => expect(approveButton).not.toBeDisabled())

    fireEvent.click(approveButton)
    await waitFor(() => expect(postRegulatoryLinkDecision).toHaveBeenCalledWith(
      CLEAN_CANDIDATE.candidate_id, 'approved', 'operator-1', 'Confirmed exact site number match.',
    ))
  })

  it('disables approve (but not reject) when the candidate has open contradictions', async () => {
    getRegulatoryLinks.mockResolvedValue({ total: 1, items: [CONFLICTING_CANDIDATE] })
    getRegulatoryLink.mockResolvedValue({
      ...CONFLICTING_CANDIDATE,
      observation: { provider: 'USGS', provider_record_id: '50038100' },
    })
    renderPage()

    await screen.findByText(/observation reports ponce/i)
    fireEvent.change(screen.getByLabelText('Actor'), { target: { value: 'operator-1' } })
    fireEvent.change(screen.getByLabelText('Rationale'), { target: { value: 'Trying to approve anyway.' } })

    const approveButton = screen.getByRole('button', { name: /approve/i })
    const rejectButton = screen.getByRole('button', { name: /reject/i })
    await waitFor(() => {
      expect(approveButton).toBeDisabled()
      expect(rejectButton).not.toBeDisabled()
    })
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderPage()
    await screen.findByText('USGS_50038100')
    await screen.findByRole('heading', { name: 'Record a decision' })

    expect(await axe(container)).toHaveNoViolations()
  })
})
