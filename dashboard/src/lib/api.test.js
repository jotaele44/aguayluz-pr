import { afterEach, describe, expect, it, vi } from 'vitest'

import { getAssets, getHealth } from '@/lib/api'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('read API failures', () => {
  it('rejects non-success responses instead of returning empty domain data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))

    await expect(getAssets()).rejects.toThrow('GET /assets failed (HTTP 503)')
  })

  it('rejects network failures so React Query can render backend-down state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network unavailable')))

    await expect(getHealth()).rejects.toThrow('GET /health failed: network unavailable')
  })
})
