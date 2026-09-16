import { afterEach, describe, expect, it, vi } from 'vitest'

import { getBarriosGeojson, getEventDensity } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('map API failure states', () => {
  it('rejects event density failures instead of reporting an empty success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))

    await expect(getEventDensity()).rejects.toThrow('HTTP 503')
  })

  it('returns null for barrios failures so the bundled GeoJSON remains eligible', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))

    await expect(getBarriosGeojson()).resolves.toBeNull()
  })
})
