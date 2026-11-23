import { afterEach, describe, expect, it, vi } from 'vitest'

import { EMPTY_WATER_USE, getWaterUseEstimates } from './water-use-api'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  vi.resetModules()
})

const respond = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  json: () => Promise.resolve(body),
})

describe('water-use API client', () => {
  it('reads /water-use/estimates and returns the body untouched', async () => {
    const body = { years: [{ year: 2020 }], counts: { records: 207, years: 3 } }
    const fetchMock = vi.fn().mockResolvedValue(respond(200, body))
    vi.stubGlobal('fetch', fetchMock)
    await expect(getWaterUseEstimates()).resolves.toEqual(body)
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/water-use\/estimates$/)
    // Read-only: the client never sends anything but a GET.
    expect(fetchMock.mock.calls[0][1]?.method ?? 'GET').toBe('GET')
  })

  it('reports a live failure instead of returning an empty collection', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(502, {})))
    await expect(getWaterUseEstimates()).rejects.toThrow(/HTTP 502 from \/water-use\/estimates/)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    await expect(getWaterUseEstimates()).rejects.toThrow(/network down/)
  })

  it('claims no estimates in the static offline export, and makes no request', async () => {
    vi.stubEnv('VITE_OFFLINE', '1')
    vi.resetModules()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const offline = await import('./water-use-api')
    await expect(offline.getWaterUseEstimates()).resolves.toEqual(offline.EMPTY_WATER_USE)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(offline.EMPTY_WATER_USE.years).toEqual([])
    expect(EMPTY_WATER_USE.counts.records).toBe(0)
  })
})
