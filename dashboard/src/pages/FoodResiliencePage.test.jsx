import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FoodResiliencePage from './FoodResiliencePage'
import { getFoodResilienceView } from '@/lib/food-resilience-api'

vi.mock('@/lib/food-resilience-api', () => ({
  getFoodResilienceView: vi.fn(),
}))

const VIEW = {
  summary: {
    state: 'WATCH',
    trend: 'UNKNOWN',
    phase: 'PHASE_1_OBSERVABLE',
    confidence: 'LOW',
    data_completeness: 0.5,
    as_of: '2026-08-26T06:18:00Z',
  },
  signals: [
    {
      signal_id: 'FOOD.P1.DROUGHT_CLASS',
      node_id: 'DROUGHT',
      state: 'WATCH',
      freshness: 'FRESH',
      observed_date: '2026-08-25',
      value: 0,
      unit: 'category',
      availability_state: 'AVAILABLE',
    },
    {
      signal_id: 'FOOD.P1.PORT_STATUS',
      node_id: 'PORTS',
      state: 'UNKNOWN',
      freshness: 'UNKNOWN',
      observed_date: null,
      value: null,
      unit: null,
      availability_state: 'MODEL_UNAVAILABLE',
    },
  ],
  baseline: {
    current_operational_baseline: false,
    records: [
      {
        metric_id: 'A.NASS2022.FARM_COUNT',
        reference_period: '2022',
        value: 7602,
        unit: 'count',
        role: 'STRUCTURAL_BASELINE',
        evidence_state: 'FACT',
      },
    ],
    current_ledger_sources: [],
  },
  scenarios: [
    {
      id: 'DYNAMIC_COVERAGE',
      required_phase: 3,
      availability: 'MODEL_UNAVAILABLE',
      tracking_issue: 'https://github.com/jotaele44/aguayluz-pr/issues/194',
    },
    {
      id: 'ROBUST_COVERAGE',
      required_phase: 4,
      availability: 'MODEL_UNAVAILABLE',
      tracking_issue: 'https://github.com/jotaele44/aguayluz-pr/issues/194',
    },
  ],
  uncertainty: { enabled: false },
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <FoodResiliencePage />
    </QueryClientProvider>,
  )
}

describe('FoodResiliencePage', () => {
  beforeEach(() => {
    getFoodResilienceView.mockResolvedValue(VIEW)
  })

  it('renders canonical phase 1 evidence and keeps phase 3/4 unavailable', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Food System Resilience' })).toBeInTheDocument()
    expect(screen.getByText('Phase 1 — observable warning indicators')).toBeInTheDocument()
    expect(screen.getByText('FOOD.P1.DROUGHT_CLASS')).toBeInTheDocument()
    expect(screen.getByText('Phase 2 — Vector A baseline ledger')).toBeInTheDocument()
    expect(screen.getByText('7602')).toBeInTheDocument()
    expect(screen.getAllByText('MODEL_UNAVAILABLE')).toHaveLength(2)
    expect(screen.getByText('Dynamic scenario estimates')).toBeInTheDocument()
    expect(screen.getByText('Robust food-resilience monitoring')).toBeInTheDocument()
  })
})
