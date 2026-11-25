import { afterEach, describe, expect, it, vi } from 'vitest'

import { EMPTY_HYDRO_SUMMARY, getAquiferWells, getHydroFeature, getHydroFeatures, getHydroSummary } from './hydro-inventory-api'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  vi.resetModules()
})

const respond = (status, body) => ({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) })

describe('hydro inventory API client', () => {
  it('reads the summary and passes list filters as query parameters, GET only', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200, { items: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await getHydroSummary()
    await getHydroFeatures({ type: 'well', q: 'aguirre', source: undefined, limit: 50, offset: 0 })
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/hydro\/inventory\/summary$/)
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/hydro\/features\?type=well&q=aguirre&limit=50&offset=0$/)
    for (const call of fetchMock.mock.calls) expect(call[1]?.method ?? 'GET').toBe('GET')
  })

  it('keeps the colons of a feature id readable in the path and asks for polygon wells only when told', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200, {}))
    vi.stubGlobal('fetch', fetchMock)
    await getHydroFeature('AQ:HA730:114:main')
    await getAquiferWells('AQ:USGS_AQFR:110SCPL', false)
    await getAquiferWells('AQ:HA730:114:main', true)
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/hydro\/features\/AQ:HA730:114:main$/)
    expect(fetchMock.mock.calls[1][0]).toMatch(/aquifer=AQ%3AUSGS_AQFR%3A110SCPL$/)
    expect(fetchMock.mock.calls[2][0]).toMatch(/include_polygon=true$/)
  })

  it('reports a live failure instead of returning an empty inventory', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(503, {})))
    await expect(getHydroSummary()).rejects.toThrow(/HTTP 503 from \/hydro\/inventory\/summary/)
  })

  it('claims no inventory in the static offline export, and makes no request', async () => {
    vi.stubEnv('VITE_OFFLINE', '1')
    vi.resetModules()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const offline = await import('./hydro-inventory-api')
    await expect(offline.getHydroSummary()).resolves.toEqual(offline.EMPTY_HYDRO_SUMMARY)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(EMPTY_HYDRO_SUMMARY.coverage).toBeNull()
  })
})
