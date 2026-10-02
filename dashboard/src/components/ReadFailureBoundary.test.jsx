import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { useQuery } from '@tanstack/react-query'
import { expect, it, vi } from 'vitest'
import { renderQueryPage } from '../test/render-query-page'
import ReadFailureBoundary from './ReadFailureBoundary'

it('hides failed results, keeps the query mounted and restores them only after retry succeeds', async () => {
  let finish
  const read = vi.fn().mockRejectedValueOnce(new Error('unavailable')).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
  function Results() {
    const { data = [] } = useQuery({ queryKey: ['read-recovery'], queryFn: read })
    return <p>{data.length} records</p>
  }
  await renderQueryPage(<ReadFailureBoundary><Results /></ReadFailureBoundary>)
  expect(await screen.findByRole('alert')).toHaveTextContent('Data unavailable')
  expect(screen.getByText('0 records')).not.toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Retry data' }))
  await waitFor(() => expect(read).toHaveBeenCalledTimes(2))
  expect(screen.getByText('0 records')).not.toBeVisible()
  await act(async () => finish(['real record']))
  expect(await screen.findByText('1 records')).toBeVisible()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('keeps optional query failures local to their view instead of hiding the whole page', async () => {
  function OptionalLayer() {
    const { isError } = useQuery({
      queryKey: ['optional-layer'],
      queryFn: () => Promise.reject(new Error('unavailable')),
      meta: { blocksViewOnError: false },
      retry: false,
    })
    return <p>{isError ? 'Optional layer unavailable' : 'Optional layer loading'}</p>
  }

  await renderQueryPage(<ReadFailureBoundary><OptionalLayer /></ReadFailureBoundary>)
  expect(await screen.findByText('Optional layer unavailable')).toBeVisible()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
