import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import StatsBar from './StatsBar'
import { useCoverage, useHealth, useReviewQueuePaged, useSummary } from '@/lib/hooks'

vi.mock('@/lib/hooks', () => ({
  useCoverage: vi.fn(),
  useHealth: vi.fn(),
  useReviewQueuePaged: vi.fn(),
  useSummary: vi.fn(),
}))

function valueFor(label) {
  return screen.getByText(label, { exact: true }).parentElement
}

describe('global summary counts', () => {
  beforeEach(() => {
    useHealth.mockReturnValue({ data: { status: 'ok', counts: { events: 26569 }, readiness: { records_review: 3 } } })
    useCoverage.mockReturnValue({ data: { assets: { mapped: 1234 } } })
    useReviewQueuePaged.mockReturnValue({ data: { total: 99, items: [{ record_ref: 'only-first-page' }] } })
    useSummary.mockReturnValue({ data: {} })
  })

  it('uses full summary totals instead of the downloaded page length', () => {
    render(<MemoryRouter><StatsBar /></MemoryRouter>)
    expect(valueFor('Mapped')).toHaveTextContent('1234')
    expect(valueFor('Events')).toHaveTextContent('26569')
    expect(valueFor('Review')).toHaveTextContent('99')
    expect(useReviewQueuePaged).toHaveBeenCalledWith({ limit: 1 })
  })

  it('preserves confirmed zero counts', () => {
    useCoverage.mockReturnValue({ data: { assets: { mapped: 0 } } })
    useReviewQueuePaged.mockReturnValue({ data: { total: 0, items: [] } })
    render(<MemoryRouter><StatsBar /></MemoryRouter>)
    expect(valueFor('Mapped')).toHaveTextContent('0')
    expect(valueFor('Review')).toHaveTextContent('0')
  })

  it('keeps unavailable counts unknown rather than inventing an empty corpus', () => {
    useHealth.mockReturnValue({ data: { status: 'down', counts: {}, readiness: {} } })
    useCoverage.mockReturnValue({ data: null })
    useReviewQueuePaged.mockReturnValue({ data: undefined })
    render(<MemoryRouter><StatsBar /></MemoryRouter>)
    for (const label of ['Mapped', 'Events', 'Review']) {
      expect(valueFor(label)).toHaveTextContent('–')
      expect(valueFor(label)).not.toHaveTextContent('0')
    }
  })
})
