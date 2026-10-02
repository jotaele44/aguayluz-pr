import { notifyManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'

const clients = new Set()

// These page tests supply immediately resolved API mocks. Keep notification
// scheduling deterministic without replacing timers or relaxing assertions.
beforeAll(() => notifyManager.setScheduler(queueMicrotask))
afterAll(() => notifyManager.setScheduler((callback) => setTimeout(callback, 0)))
afterEach(() => {
  for (const client of clients) client.clear()
  clients.clear()
})

export async function renderQueryPage(page) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  clients.add(client)
  let rendered
  await act(async () => {
    rendered = render(<QueryClientProvider client={client}>{page}</QueryClientProvider>)
  })
  return rendered
}
