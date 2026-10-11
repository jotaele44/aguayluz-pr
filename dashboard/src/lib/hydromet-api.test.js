import { afterEach, describe, expect, it, vi } from 'vitest'

import { getRiverGauges, getRiverGaugesGeojson, postHydrometRefresh } from './hydromet-api'

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

const respond = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  json: () => Promise.resolve(body),
})

describe('hydromet API client', () => {
  it('omits false filters from the gauge query', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200, { total: 0, items: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await getRiverGauges({ flooding_only: false })
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/hydromet\/gauges$/)
    await getRiverGauges({ flooding_only: true })
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/hydromet\/gauges\?flooding_only=true$/)
  })

  it('falls back to an empty collection when the backend is down', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    await expect(getRiverGaugesGeojson()).resolves.toEqual({ type: 'FeatureCollection', features: [] })
  })

  it('explains auth, busy and failed refreshes instead of reporting success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(401, {})))
    await expect(postHydrometRefresh('nwps_gauges')).rejects.toThrow(/API key auth is enabled/)

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(409, {})))
    await expect(postHydrometRefresh('nwps_gauges')).rejects.toThrow(/already running/)

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(502, {
      ok: false,
      steps: [{ script: 'scripts/ingest_nwps_gauges.py', return_code: 1, stderr_tail: 'bulk fetch failed' }],
    })))
    await expect(postHydrometRefresh('nwps_gauges')).rejects.toThrow(/ingest_nwps_gauges.py: bulk fetch failed/)
  })

  it('posts to the source refresh endpoint and returns the result', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(postHydrometRefresh('nwps_gauges')).resolves.toEqual({ ok: true })
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/hydromet\/refresh\/nwps_gauges$/)
    expect(fetchMock.mock.calls[0][1].method).toBe('POST')
  })
})
