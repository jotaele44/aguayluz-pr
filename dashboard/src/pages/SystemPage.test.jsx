import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SystemPage from '@/pages/SystemPage'

const runExport = vi.fn()
const resetExport = vi.fn()
const refreshStatus = vi.fn()
const postNotify = vi.fn()
const setApiKey = vi.fn()
const toast = vi.fn()
let systemQuery
let exportMutation

const status = {
  auth_enabled: true,
  slack_configured: true,
  ntfy_configured: false,
  email_configured: false,
  ai_enabled: true,
  sentry_dsn_set: false,
  artifacts: {
    hub_export: {
      present: true,
      path: 'outputs/hub_export.json',
      bytes: 2048,
      modified_at: '2026-08-19T05:00:00Z',
    },
  },
  corpora: {},
}

vi.mock('@/lib/hooks', () => ({
  useSystemStatus: () => systemQuery,
  useHealth: () => ({ data: { status: 'ok', counts: {} }, isError: false }),
  useRunExport: () => exportMutation,
}))

vi.mock('@/lib/api', () => ({
  getApiKey: () => 'session-key',
  setApiKey: (...args) => setApiKey(...args),
  getReportUrl: () => 'http://localhost:8000/export/report.html',
  postNotify: (...args) => postNotify(...args),
}))

vi.mock('@/components/ui/use-toast', () => ({
  useToast: () => ({ toast }),
}))

describe('SystemPage operator workflows', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    systemQuery = {
      data: status,
      isLoading: false,
      isFetching: false,
      refetch: refreshStatus,
    }
    exportMutation = {
      mutate: runExport,
      isPending: false,
      isSuccess: false,
      isError: false,
      error: null,
      reset: resetExport,
    }
  })

  const sendNotification = () => {
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Boil water notice' } })
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Use bottled water until noon.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send notification' }))
  }

  it('derives full-success feedback from confirmed successful channels', async () => {
    postNotify.mockResolvedValue({
      ok: true,
      channels_active: true,
      attempted_channels: ['slack'],
      succeeded_channels: ['slack'],
      failed_channels: [],
      errors: [],
    })
    render(<SystemPage />)

    sendNotification()

    await waitFor(() => expect(postNotify).toHaveBeenCalledWith({
      title: 'Boil water notice',
      message: 'Use bottled water until noon.',
    }))
    expect(await screen.findByText('Notification sent to slack.')).toHaveAttribute('role', 'status')
  })

  it('reports partial delivery from confirmed successes and failures', async () => {
    postNotify.mockResolvedValue({
      ok: false,
      channels_active: true,
      attempted_channels: ['slack', 'ntfy'],
      succeeded_channels: ['slack'],
      failed_channels: [{ channel: 'ntfy', error: 'push rejected' }],
      errors: ['ntfy: push rejected'],
    })
    render(<SystemPage />)

    sendNotification()

    expect(await screen.findByText('Notification sent to slack. Failed: ntfy: push rejected.')).toHaveAttribute('role', 'status')
  })

  it('never reports configured channels as delivered when every attempt failed', async () => {
    postNotify.mockResolvedValue({
      ok: false,
      channels_active: true,
      attempted_channels: ['slack'],
      succeeded_channels: [],
      failed_channels: [{ channel: 'slack', error: 'webhook unavailable' }],
      errors: ['slack: webhook unavailable'],
    })
    render(<SystemPage />)

    sendNotification()

    expect(await screen.findByText('Notification delivery failed: slack: webhook unavailable.')).toHaveAttribute('role', 'alert')
    expect(screen.queryByText(/notification sent to/i)).not.toBeInTheDocument()
  })

  it('shows credential presence without rendering backend secret values', () => {
    render(<SystemPage />)

    expect(screen.getByText('API key auth')).toBeInTheDocument()
    expect(screen.getByText('ANTHROPIC_API_KEY')).toBeInTheDocument()
    expect(screen.getByLabelText('API key')).toHaveAttribute('type', 'password')
    expect(screen.getByText(/never reads or displays their values/i)).toBeInTheDocument()
    expect(screen.queryByText('outputs/hub_export.json')).not.toBeInTheDocument()
  })

  it('runs exports and exposes artifact status refresh', () => {
    render(<SystemPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Run federation export' }))
    expect(resetExport).toHaveBeenCalled()
    expect(runExport).toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Refresh export status' }))
    expect(refreshStatus).toHaveBeenCalled()
    expect(screen.getByText('Hub export')).toBeInTheDocument()
    expect(screen.getByText('Generated artifact')).toBeInTheDocument()
  })

  it('announces loading and unavailable status distinctly', () => {
    systemQuery = {
      data: null,
      isLoading: true,
      isFetching: true,
      refetch: refreshStatus,
    }
    const { rerender } = render(<SystemPage />)

    expect(screen.getByText('Loading export status…')).toHaveAttribute('role', 'status')
    expect(screen.getByText('Loading source status…')).toHaveAttribute('role', 'status')
    expect(screen.getAllByText('checking')).toHaveLength(6)
    expect(screen.queryByText('absent')).not.toBeInTheDocument()
    expect(screen.getByText('Checking backend authentication status…')).toHaveAttribute('role', 'status')

    systemQuery = {
      data: null,
      isLoading: false,
      isFetching: false,
      refetch: refreshStatus,
    }
    rerender(<SystemPage />)

    expect(screen.getByText('Export status is unavailable.')).toHaveAttribute('role', 'alert')
    expect(screen.getByText('Source status is unavailable.')).toHaveAttribute('role', 'alert')
    expect(screen.getByText(/credential presence is unavailable/i)).toHaveAttribute('role', 'alert')
    expect(screen.getAllByText('unavailable')).toHaveLength(6)
    expect(screen.queryByText('absent')).not.toBeInTheDocument()
    expect(screen.getByText(/no assumption is made/i)).toHaveAttribute('role', 'alert')
  })
})
