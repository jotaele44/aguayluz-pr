import { fireEvent, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderQueryPage } from '@/test/render-query-page'
import { useDecision, useReviewQueuePaged } from '@/lib/hooks'
import ReviewPage from '@/pages/ReviewPage'

const { toast } = vi.hoisted(() => ({ toast: vi.fn() }))

vi.mock('@/lib/hooks', () => ({
  useDecision: vi.fn(),
  useReviewQueuePaged: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  postAiQuery: vi.fn(),
}))

vi.mock('@/components/ui/use-toast', () => ({
  useToast: () => ({ toast }),
}))

describe('ReviewPage keyboard shortcuts', () => {
  let decide

  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    })
    decide = vi.fn().mockResolvedValue(undefined)
    vi.mocked(useDecision).mockReturnValue({ mutateAsync: decide, isPending: false })
    vi.mocked(useReviewQueuePaged).mockReturnValue({
      data: {
        total: 1,
        items: [{
          record_ref: 'event-1',
          severity: 'high',
          reason: 'Review the source record',
          review_binding: { source: 'event' },
        }],
      },
      isLoading: false,
    })
  })

  it('does not apply row shortcuts while focus is on an action button', async () => {
    await renderQueryPage(<MemoryRouter><ReviewPage /></MemoryRouter>)

    fireEvent.keyDown(screen.getByRole('button', { name: 'Accept' }), { key: 'a' })

    expect(decide).not.toHaveBeenCalled()
  })

  it('keeps row shortcuts active when focus is outside interactive controls', async () => {
    await renderQueryPage(<MemoryRouter><ReviewPage /></MemoryRouter>)

    fireEvent.keyDown(window, { key: 'a' })

    await waitFor(() => expect(decide).toHaveBeenCalledWith({
      ref: 'event-1',
      decision: 'accept',
      sourceBinding: { source: 'event' },
    }))
  })
})
