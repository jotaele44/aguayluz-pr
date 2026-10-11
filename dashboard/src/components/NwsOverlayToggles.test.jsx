import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import NwsOverlayToggles from './NwsOverlayToggles'
import {
  CLOUDGIS_HOST,
  NWS_CLOUDGIS_OVERLAYS,
  OVERLAY_REFRESH_MS,
  overlayForError,
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

  it('maps a MapLibre error back to its overlay only', () => {
    expect(overlayForError({ sourceId: overlaySourceId('nws-radar') })).toBe('nws-radar')
    expect(overlayForError({ source: { id: overlaySourceId('nws-warnings') } })).toBe('nws-warnings')
    expect(overlayForError({ sourceId: 'osm' })).toBeNull()
    expect(overlayForError(undefined)).toBeNull()
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

  it('shows live status and per-overlay failures for active overlays', () => {
    render(
      <NwsOverlayToggles
        active={{ 'nws-radar': true, 'nws-warnings': true }}
        errors={{ 'nws-warnings': 'HTTP 503' }}
        loadedAt={{ 'nws-radar': Date.UTC(2026, 9, 11, 12, 0) }}
        onToggle={() => {}}
      />,
    )
    expect(screen.getByRole('button', { name: 'NWS radar' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText(/NWS radar: live · requested/)).toBeInTheDocument()
    expect(screen.getByText(/NWS warnings: unavailable from NWS \(HTTP 503\)/)).toBeInTheDocument()
    expect(screen.getByText(/not stored or validated by AguaYLuz/)).toBeInTheDocument()
  })
})
