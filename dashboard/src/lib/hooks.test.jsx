import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { useDecision } from './hooks'
import { postDecision } from './api'

vi.mock('./api', async (original) => ({ ...await original(), postDecision: vi.fn() }))

describe('review optimistic cache', () => {
  it('restores failed decisions without changing unrelated filtered totals', async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const firstKey = ['review/paged', { severity: 'block' }]
    const otherKey = ['review/paged', { severity: 'warn' }]
    const first = { total: 10, items: [{ record_ref: 'first' }] }
    const other = { total: 20, items: [{ record_ref: 'other' }] }
    client.setQueryData(firstKey, first)
    client.setQueryData(otherKey, other)
    let rejectRequest
    postDecision.mockImplementation(() => new Promise((_, reject) => { rejectRequest = reject }))
    const { result, unmount } = renderHook(() => useDecision(), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    })
    let mutation
    await act(async () => {
      mutation = result.current.mutateAsync({ ref: 'first', decision: 'accept' }).catch((error) => error)
      await vi.waitFor(() => expect(rejectRequest).toBeTypeOf('function'))
    })
    expect(client.getQueryData(firstKey)).toEqual({ total: 9, items: [] })
    expect(client.getQueryData(otherKey)).toEqual(other)
    await act(async () => {
      rejectRequest(new Error('unavailable'))
      expect(await mutation).toBeInstanceOf(Error)
    })
    expect(client.getQueryData(firstKey)).toEqual(first)
    expect(client.getQueryData(otherKey)).toEqual(other)
    unmount()
    client.clear()
  })
})
