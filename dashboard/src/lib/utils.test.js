import { describe, it, expect } from 'vitest';

import { lookup } from '@/lib/utils';

// lookup() exists because `MAP[key] ?? fallback` is not a safe miss. Object
// literals inherit from Object.prototype, so a handful of ordinary-looking
// strings resolve to something truthy and `??` never fires. Every assertion here
// contrasts lookup() against the bare index it replaced, because "returns the
// fallback" is only interesting if the thing it replaced did not.

const MAP = { power: 'amber', water: 'sky' };

// The inherited keys that resolve to something truthy on any object literal.
const INHERITED = ['__proto__', 'constructor', 'toString', 'valueOf', 'hasOwnProperty'];

describe('lookup', () => {
  it('returns a real value for a real key', () => {
    expect(lookup(MAP, 'power', 'fallback')).toBe('amber');
    expect(lookup(MAP, 'water', 'fallback')).toBe('sky');
  });

  it('returns the fallback for an ordinary miss', () => {
    expect(lookup(MAP, 'geothermal', 'fallback')).toBe('fallback');
    expect(lookup(MAP, '', 'fallback')).toBe('fallback');
  });

  it('returns the fallback for undefined and null keys', () => {
    expect(lookup(MAP, undefined, 'fallback')).toBe('fallback');
    expect(lookup(MAP, null, 'fallback')).toBe('fallback');
  });

  it.each(INHERITED)('returns the fallback for the inherited key %s', (key) => {
    expect(lookup(MAP, key, 'fallback')).toBe('fallback');
  });

  it.each(INHERITED)('the bare index it replaces does NOT fall back for %s', (key) => {
    // The premise of this whole module in one assertion. If this ever starts
    // failing, JavaScript changed and lookup() is no longer needed.
    expect(MAP[key] ?? 'fallback').not.toBe('fallback');
  });

  it('returns a genuinely stored falsy value rather than the fallback', () => {
    // hasOwn, not truthiness: a map may legitimately store 0, '' or false.
    const falsy = { zero: 0, empty: '', no: false, nothing: undefined };

    expect(lookup(falsy, 'zero', 'fallback')).toBe(0);
    expect(lookup(falsy, 'empty', 'fallback')).toBe('');
    expect(lookup(falsy, 'no', 'fallback')).toBe(false);
  });

  it('returns an explicitly stored undefined as undefined, not as the fallback', () => {
    // The one place hasOwn and `??` genuinely differ in the other direction.
    // Storing undefined is a statement that the key exists and has no value.
    expect(lookup({ nothing: undefined }, 'nothing', 'fallback')).toBeUndefined();
  });

  it('accepts numeric keys, which arrive as strings on object literals', () => {
    const severities = { 0: 'info', 4: 'severe' };

    expect(lookup(severities, 4, '—')).toBe('severe');
    expect(lookup(severities, '4', '—')).toBe('severe');
    expect(lookup(severities, 9, '—')).toBe('—');
  });
});
