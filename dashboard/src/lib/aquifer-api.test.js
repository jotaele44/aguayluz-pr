import { afterEach, describe, expect, it, vi } from 'vitest'

import { EMPTY_AQUIFER_BANDS, getAquiferBands } from './aquifer-api'

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

describe('aquifer API client', () => {
  it('reads /aquifer/bands and returns the body untouched', async () => {
    const body = { items: [{ site_no: '175947066130601' }], counts: { wells: 1 } }
    const fetchMock = vi.fn().mockResolvedValue(respond(200, body))
    vi.stubGlobal('fetch', fetchMock)
    await expect(getAquiferBands()).resolves.toEqual(body)
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/aquifer\/bands$/)
    // Read-only: the client never sends anything but a GET.
    expect(fetchMock.mock.calls[0][1]?.method ?? 'GET').toBe('GET')
  })

  it('reports a live failure instead of returning an empty collection', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(502, {})))
    await expect(getAquiferBands()).rejects.toThrow(/HTTP 502 from \/aquifer\/bands/)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    await expect(getAquiferBands()).rejects.toThrow(/network down/)
  })

  it('claims no wells in the static offline export, and makes no request', async () => {
    vi.stubEnv('VITE_OFFLINE', '1')
    vi.resetModules()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const offline = await import('./aquifer-api')
    await expect(offline.getAquiferBands()).resolves.toEqual(offline.EMPTY_AQUIFER_BANDS)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(offline.EMPTY_AQUIFER_BANDS.items).toEqual([])
    expect(EMPTY_AQUIFER_BANDS.counts.wells).toBe(0)
  })
})
