import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// A browser without WebGL2 makes the MapLibre constructor throw. The /map page
// must say so instead of rendering nothing.
vi.mock('maplibre-gl', () => ({
  setWorkerUrl: vi.fn(),
  Map: vi.fn().mockImplementation(function MapWithoutWebGL() {
    throw new Error('WebGL2 is required to display this map.')
  }),
  NavigationControl: vi.fn(),
  Popup: vi.fn(),
}))
vi.mock('maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url', () => ({ default: 'worker.js' }))

import AssetMap from './AssetMap'

const EMPTY = { type: 'FeatureCollection', features: [] }

describe('AssetMap without WebGL', () => {
  it('shows why the map is unavailable instead of a blank page', () => {
    render(<AssetMap assets={EMPTY} municipios={EMPTY} barrios={EMPTY} alerts={[]} gauges={[]} />)
    expect(screen.getByRole('status').textContent).toContain('Map unavailable: WebGL2 is required')
  })
})
