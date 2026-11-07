import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SpatialToolsPanel } from './SpatialToolsPanel'
import { PROXY_LABEL } from '../lib/gis/networkApi'

function baseState(overrides) {
  return {
    mode: 'off', setMode: vi.fn(), targetKey: '', setTargetKey: vi.fn(), targetKeys: [],
    measurePoints: [], measureLengthKm: 0, bufferRadiusKm: 5, setBufferRadiusKm: vi.fn(),
    bufferResult: null, nearestResult: null, clearAll: vi.fn(),
    gisEnabled: true, exportable: () => false, drawVertices: [], drawAreaM2: 0,
    identifyState: { status: 'idle' }, queryState: { status: 'idle' }, exportError: null,
    runPolygonQuery: vi.fn(), exportPolygonQuery: vi.fn(),
    traceDirection: 'downstream', setTraceDirection: vi.fn(), traceState: { status: 'idle' },
    scenarioSelection: [], scenarioState: { status: 'idle' }, runScenario: vi.fn(),
    ...overrides,
  }
}

const proxyHit = {
  feature_id: 'PMP_1', layer_id: 'water_assets', node_type: 'hydro_asset', hops: 1,
  edge_id: 'E1', relation: 'energizes', confidence: 47, evidence_required: true,
}

describe('SpatialToolsPanel dependency and scenario modes', () => {
  it('offers the backend modes only when a GIS client is wired', () => {
    const { rerender } = render(<SpatialToolsPanel {...baseState({})} />)
    expect(screen.getByRole('button', { name: 'Dependencies' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Scenario' })).toBeTruthy()
    rerender(<SpatialToolsPanel {...baseState({ gisEnabled: false })} />)
    expect(screen.queryByRole('button', { name: 'Scenario' })).toBeNull()
  })

  it('labels traces that used proximity-proxy links and shows link confidence', () => {
    render(<SpatialToolsPanel {...baseState({
      mode: 'trace',
      traceState: {
        status: 'ready',
        asset: { feature_id: 'PWR1', properties: { asset_name: 'Substation X' } },
        data: { direction: 'downstream', hits: [proxyHit], unverified_links_used: true, evidence_state: 'COMPUTED' },
      },
    })} />)
    expect(screen.getByRole('note').textContent).toContain(PROXY_LABEL)
    expect(screen.getByText(/confidence 47%/)).toBeTruthy()
  })

  it('presents scenario results as a non-persisted hypothesis with affected areas', () => {
    render(<SpatialToolsPanel {...baseState({
      mode: 'scenario',
      scenarioSelection: [{ layer_id: 'power_assets', feature_id: 'PWR1', label: 'Substation X' }],
      scenarioState: {
        status: 'ready',
        data: {
          impacted: [proxyHit], unverified_links_used: true,
          affected_areas: [{ area_type: 'municipio', area_id: '72011', name: 'Añasco' }],
          notes: ['note one'],
        },
      },
    })} />)
    expect(screen.getByText('HYPOTHESIS · not persisted')).toBeTruthy()
    expect(screen.getByRole('note').textContent).toContain(PROXY_LABEL)
    expect(screen.getByText(/Affected areas: Añasco/)).toBeTruthy()
  })

  it('does not show the proxy label when every link is verified', () => {
    render(<SpatialToolsPanel {...baseState({
      mode: 'trace',
      traceState: {
        status: 'ready',
        asset: { feature_id: 'PWR1', properties: {} },
        data: { direction: 'downstream', hits: [{ ...proxyHit, evidence_required: false }], unverified_links_used: false, evidence_state: 'COMPUTED' },
      },
    })} />)
    expect(screen.queryByRole('note')).toBeNull()
  })
})
