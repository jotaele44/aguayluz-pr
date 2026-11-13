import { afterEach, describe, expect, it, vi } from 'vitest'

import { getSolidWasteSites, SOLID_WASTE_KINDS } from './environmental-exposure-api'

afterEach(() => {
  vi.unstubAllGlobals()
})

const respond = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  json: () => Promise.resolve(body),
})

const kindOf = (url) => new URL(url, 'http://x').searchParams.get('entity_kind')

describe('getSolidWasteSites', () => {
  it('asks the existing entities endpoint once per solid-waste kind, read-only', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200, { total: 0, items: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await getSolidWasteSites()
    expect(fetchMock).toHaveBeenCalledTimes(SOLID_WASTE_KINDS.length)
    const urls = fetchMock.mock.calls.map(([url]) => url)
    expect(urls.every((url) => /\/environmental-exposure\/entities\?/.test(url))).toBe(true)
    // Pinned literally, not read back from the constant: dropping DISPOSAL_SITE would
    // silently hide the unauthorized-dump records ADR-0004 reserves that kind for.
    expect(SOLID_WASTE_KINDS).toEqual(['LANDFILL', 'SOLID_WASTE_FACILITY', 'DISPOSAL_SITE'])
    expect(urls.map(kindOf).sort()).toEqual(['DISPOSAL_SITE', 'LANDFILL', 'SOLID_WASTE_FACILITY'])
    expect(fetchMock.mock.calls.every(([, init]) => (init?.method ?? 'GET') === 'GET')).toBe(true)
  })

  it('merges the items and sums the server totals, not the item counts', async () => {
    const pages = {
      LANDFILL: { total: 600, items: [{ entity_id: 'a' }, { entity_id: 'b' }] },
      SOLID_WASTE_FACILITY: { total: 1, items: [{ entity_id: 'c' }] },
      DISPOSAL_SITE: { total: 0, items: [] },
    }
    vi.stubGlobal('fetch', vi.fn((url) => Promise.resolve(respond(200, pages[kindOf(url)]))))
    const result = await getSolidWasteSites()
    expect(result.items.map((item) => item.entity_id).sort()).toEqual(['a', 'b', 'c'])
    // 601 reported against 3 received: a caller can see the list is truncated.
    expect(result.total).toBe(601)
  })

  it('reports an empty list, never a partial success, when every request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(500, {})))
    await expect(getSolidWasteSites()).resolves.toEqual({ total: 0, items: [] })
  })
})
