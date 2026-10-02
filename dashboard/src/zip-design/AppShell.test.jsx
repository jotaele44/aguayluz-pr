import { lazy } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import AppShell from './AppShell'

vi.mock('../components/StatsBar', () => ({ default: () => <div>Summary counts</div> }))
vi.mock('../components/AiQueryPanel', () => ({ default: () => null }))

it('keeps navigation usable while a lazy route is suspended', async () => {
  let resolvePage
  const PendingPage = lazy(() => new Promise((resolve) => { resolvePage = resolve }))
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Routes><Route element={<AppShell />}>
    <Route path="/" element={<PendingPage />} />
    <Route path="/assets" element={<p>Assets ready</p>} />
  </Route></Routes></MemoryRouter></QueryClientProvider>)
  expect(screen.getByRole('status')).toHaveTextContent('Loading view')
  expect(screen.getByText('Summary counts')).toBeVisible()
  const assets = screen.getAllByRole('link', { name: 'Assets', exact: true })[0]
  expect(assets).toBeVisible()
  const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
  await act(async () => { assets.dispatchEvent(click) })
  expect(click.defaultPrevented).toBe(true)
  expect(document.querySelector('main')).toHaveTextContent('Assets ready')
  await act(async () => resolvePage({ default: () => <p>Late overview</p> }))
  expect(screen.queryByText('Late overview')).not.toBeInTheDocument()
})
