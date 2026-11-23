import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

// The dashboard is dark-only. On its backgrounds, slate-500, slate-600 and
// slate-700 text measures 2.4:1 to 4.2:1, below the 4.5:1 that normal-size
// text needs; the federation browser scan found it on 19 of 20 routes. Dim
// text uses slate-400 instead. This test keeps the failing shades from coming
// back as text colours. Borders and backgrounds in those shades are fine.
const SRC = join(__dirname, '..');
const FAILING = /(?<![\w-])(?:[a-z-]+:)*text-slate-(?:500|600|700)(?![\w/-])/g;

function sources(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(jsx?|css)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

describe('dim text colours', () => {
  it('does not use slate-500, slate-600 or slate-700 as a text colour', () => {
    const offenders = sources(SRC).flatMap((path) => {
      const found = readFileSync(path, 'utf8').match(FAILING) || [];
      return found.length ? [`${relative(SRC, path)}: ${[...new Set(found)].join(', ')}`] : [];
    });

    expect(offenders).toEqual([]);
  });

  it('recognises the classes it guards against, with and without variants', () => {
    const sample = 'text-slate-500 hover:text-slate-600 placeholder:text-slate-700 text-slate-400 border-slate-600';

    expect(sample.match(FAILING)).toEqual(['text-slate-500', 'hover:text-slate-600', 'placeholder:text-slate-700']);
  });
});
