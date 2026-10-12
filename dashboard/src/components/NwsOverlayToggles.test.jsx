import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import NwsOverlayToggles from './NwsOverlayToggles'
import {
  CLOUDGIS_HOST,
  NWS_CLOUDGIS_OVERLAYS,
  OVERLAY_REFRESH_MS,
  overlayForEvent,
  overlaySourceId,
  overlayTileUrl,
} from '@/lib/nws-cloudgis-overlays'

describe('NWS CloudGIS overlay definitions', () => {
  it('point at the live CloudGIS host with a per-tile bbox and a time bucket', () => {
    for (const overlay of NWS_CLOUDGIS_OVERLAYS) {
      const url = overlayTileUrl(overlay, 3 * OVERLAY_REFRESH_MS + 1)
      expect(url.startsWith(`${CLOUDGIS_HOST}/eventdriven/rest/services/`)).toBe(true)
      expect(url).toContain('bbox={bbox-epsg-3857}')
      expect(url).toContain('/MapServer/export?')
      expect(url.endsWith('&_t=3')).toBe(true)
    }
    expect(CLOUDGIS_HOST).not.toContain('idpgis')
  })

  it('maps a MapLibre error or tile event back to its overlay only', () => {
    expect(overlayForEvent({ sourceId: overlaySourceId('nws-radar') })).toBe('nws-radar')
    expect(overlayForEvent({ source: { id: overlaySourceId('nws-warnings') } })).toBe('nws-warnings')
    expect(overlayForEvent({ sourceId: 'osm' })).toBeNull()
    expect(overlayForEvent(undefined)).toBeNull()
  })
})

describe('NwsOverlayToggles', () => {
  it('toggles an overlay and labels the group display only', () => {
    const onToggle = vi.fn()
    render(<NwsOverlayToggles active={{}} onToggle={onToggle} />)
    const radar = screen.getByRole('button', { name: 'NWS radar' })
    expect(radar).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(radar)
    expect(onToggle).toHaveBeenCalledWith('nws-radar')
    expect(screen.getByText(/display only/)).toBeInTheDocument()
    expect(screen.queryByText(/not stored or validated/)).toBeNull()
  })

  it('shows loading, live and failed states per active overlay', () => {
    const { rerender } = render(
      <NwsOverlayToggles
        active={{ 'nws-radar': true, 'nws-warnings': true }}
        status={{
          'nws-radar': { state: 'live', at: Date.UTC(2026, 9, 11, 12, 0) },
          'nws-warnings': { state: 'error', at: Date.UTC(2026, 9, 11, 12, 0), message: 'HTTP 503' },
        }}
        onToggle={() => {}}
      />,
    )
    expect(screen.getByRole('button', { name: 'NWS radar' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText(/NWS radar: live · tiles loaded/)).toBeInTheDocument()
    expect(screen.getByText(/NWS warnings: unavailable from NWS \(HTTP 503\)/)).toBeInTheDocument()
    expect(screen.getByText(/not stored or validated by AguaYLuz/)).toBeInTheDocument()
    // A later successful tile load replaces the error; a just-toggled overlay is pending.
    rerender(
      <NwsOverlayToggles
        active={{ 'nws-radar': true, 'nws-warnings': true }}
        status={{ 'nws-radar': { state: 'loading', at: 0 }, 'nws-warnings': { state: 'live', at: 0 } }}
        onToggle={() => {}}
      />,
    )
    expect(screen.getByText(/NWS radar: loading from NWS/)).toBeInTheDocument()
    expect(screen.getByText(/NWS warnings: live · tiles loaded/)).toBeInTheDocument()
    expect(screen.queryByText(/unavailable from NWS/)).toBeNull()
  })
})
