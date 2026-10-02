import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getBarriosGeojson, getEventDensity } from './api'

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('VITE_OFFLINE', '0')
  vi.stubGlobal('fetch', vi.fn())
  window.sessionStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('map API failure states', () => {
  it('rejects event density failures instead of reporting an empty success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))
    await expect(getEventDensity()).rejects.toThrow('HTTP 503')
  })

  it('rejects barrios failures instead of reporting an empty success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))
    await expect(getBarriosGeojson()).rejects.toThrow('HTTP 503')
  })
})

describe('review decisions', () => {
  it.each([400, 403, 404, 409, 422, 500, 503])('rejects HTTP %s so optimistic rows can be restored', async (status) => {
    fetch.mockResolvedValue(new Response('{"detail":"rejected"}', { status }))
    const { postDecision } = await import('./api')
    await expect(postDecision('a/b', 'accept')).rejects.toThrow(`HTTP ${status}`)
  })

  it('returns the confirmed decision and encodes the record reference', async () => {
    fetch.mockResolvedValue(new Response('{"ok":true}'))
    const { postDecision, setApiKey } = await import('./api')
    setApiKey('test-only-key')
    await expect(postDecision('a/b', 'accept', 'a'.repeat(64))).resolves.toEqual({ ok: true })
    expect(fetch.mock.calls[0][0]).toContain('a%2Fb/decision')
    const [, request] = fetch.mock.calls[0]
    expect(request.method).toBe('POST')
    expect(request.headers.Authorization).toBeTruthy()
    expect(request.body).toBe(JSON.stringify({ decision: 'accept', source_binding: 'a'.repeat(64) }))
  })

  it('gives actionable authentication guidance', async () => {
    fetch.mockResolvedValue(new Response('{}', { status: 401 }))
    const { postDecision } = await import('./api')
    await expect(postDecision('record', 'accept')).rejects.toThrow('Set the key in System & Tools')
  })
})

describe('offline writes', () => {
  it.each(['postDecision', 'postRunExport', 'patchEvent', 'patchAsset'])('%s refuses to report unsaved changes as successful', async (name) => {
    vi.stubEnv('VITE_OFFLINE', '1')
    const api = await import('./api')
    await expect(api[name]('record', {})).rejects.toThrow('offline mode')
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('structured error clients', () => {
  it.each(['postAiQuery', 'postNotify'])('%s returns an error for malformed response JSON', async (name) => {
    fetch.mockResolvedValue(new Response('not json'))
    const api = await import('./api')
    const result = await api[name]({ message: 'test', title: 'test' })
    expect(result.error).toBeTruthy()
    expect(result.answer ?? result.ok).toBeFalsy()
  })
})

describe('read failures are not empty results', () => {
  it.each([
    ['./api', 'getAssets'], ['./api', 'getLumaOutageStatus'], ['./api', 'getActiveOutageCount'],
    ['./cave-karst-api', 'getCaveKarstAssets'],
    ['./environmental-exposure-api', 'getEnvironmentalExposureEntities'],
    ['./regulatory-api', 'getRegulatoryObservations'],
  ])('%s preserves HTTP, parsing and network failures', async (module, method) => {
    const api = await import(module)
    fetch.mockResolvedValueOnce(new Response('{}', { status: 503 }))
    await expect(api[method]()).rejects.toThrow('HTTP 503')
    fetch.mockResolvedValueOnce(new Response('not json'))
    await expect(api[method]()).rejects.toThrow()
    fetch.mockRejectedValueOnce(new TypeError('network unavailable'))
    await expect(api[method]()).rejects.toThrow('network unavailable')
    fetch.mockResolvedValueOnce(new Response('[]'))
    await expect(api[method]()).resolves.toEqual([])
  })
})

describe('outage sources remain distinct', () => {
  it('preserves raw regional status alongside the active event count', async () => {
    const regional = { total: 1, latest: { raw_payload: { region: 'Ponce' } }, schema_state: 'RAW_UNFROZEN' }
    const active = { total: 702, offset: 0, items: [] }
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(regional)))
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(active)))
    const { getLumaOutageStatus, getActiveOutageCount } = await import('./api')
    await expect(getLumaOutageStatus({ limit: 2 })).resolves.toEqual(regional)
    await expect(getActiveOutageCount()).resolves.toEqual(active)
    expect(fetch.mock.calls[0][0]).toMatch(/\/outages\/status\?limit=2$/)
    expect(fetch.mock.calls[1][0]).toMatch(/\/events\?type=outage&active=true&limit=0$/)
  })
})
