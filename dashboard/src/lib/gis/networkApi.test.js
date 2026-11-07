import { describe, expect, it, vi } from 'vitest'
import { PROXY_LABEL, createNetworkClient, evidenceText, linesForEdges } from './networkApi'

describe('network client', () => {
  it('builds trace URLs and posts scenario selections', async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ hits: [] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ impacted: [] }), { status: 200 }))
    const client = createNetworkClient('http://api', fetchImpl)
    await client.trace('PWR00039', 'upstream', 5)
    expect(fetchImpl.mock.calls[0][0]).toBe('http://api/gis/trace?feature_id=PWR00039&direction=upstream&max_hops=5')
    await client.scenario([{ layer_id: 'power_assets', feature_id: 'PWR00039' }])
    expect(JSON.parse(fetchImpl.mock.calls[1][1].body)).toEqual({
      selected: [{ layer_id: 'power_assets', feature_id: 'PWR00039' }], max_hops: 25,
    })
  })

  it('surfaces backend error details', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'bad' }), { status: 422 }))
    await expect(createNetworkClient('http://api', fetchImpl).trace('x')).rejects.toThrow('HTTP 422: bad')
  })
})

describe('evidence helpers', () => {
  it('keeps only the links a result used', () => {
    const collection = { features: [{ properties: { edge_id: 'A' } }, { properties: { edge_id: 'B' } }] }
    expect(linesForEdges(collection, ['B']).features).toEqual([{ properties: { edge_id: 'B' } }])
    expect(linesForEdges(null, ['B']).features).toEqual([])
  })

  it('labels proxy links and unknown confidence', () => {
    expect(evidenceText({ relation: 'energizes', confidence: 47, evidence_required: true }))
      .toBe(`energizes · confidence 47% · ${PROXY_LABEL}`)
    expect(evidenceText({ relation: 'supplies', confidence: null, evidence_required: false }))
      .toBe('supplies · confidence unknown')
  })
})
