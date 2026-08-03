import { describe, it, expect } from 'vitest';

import { toCSV } from '@/lib/csv';

// toCSV backs every "export" button in the dashboard. It is eleven lines, and
// every one of them is a decision: whether to emit anything at all, where the
// columns come from, what a null becomes, and when a value has to be quoted.
// Getting the quoting wrong produces a file that opens without complaint and is
// silently misaligned, which is the worst failure mode available here.

describe('toCSV', () => {
  it('returns an empty string for no rows, rather than a bare header', () => {
    // A header-only file looks like a successful export of nothing. An empty one
    // is at least obviously empty.
    expect(toCSV([])).toBe('');
    expect(toCSV([], ['a', 'b'])).toBe('');
  });

  it('infers the columns from the first row when none are given', () => {
    expect(toCSV([{ id: 1, name: 'PRASA' }])).toBe('id,name\n1,PRASA');
  });

  it('uses the given columns for order and for selection', () => {
    // Explicit columns both reorder and drop — the second is what keeps internal
    // fields out of an exported file.
    expect(toCSV([{ id: 1, name: 'PRASA', secret: 'x' }], ['name', 'id']))
      .toBe('name,id\nPRASA,1');
  });

  it('leaves a cell blank when a later row lacks an inferred column', () => {
    // Columns come from the *first* row only, so ragged data must not shift the
    // remaining cells left.
    expect(toCSV([{ a: 1, b: 2 }, { a: 3 }])).toBe('a,b\n1,2\n3,');
  });

  it('blanks null and undefined but keeps falsy values that are data', () => {
    // `v ?? ''`, not `v || ''`. A reading of 0 and a flag of false are
    // measurements; blanking them would turn a real value into a missing one.
    expect(toCSV([{ a: null, b: undefined, c: 0, d: false, e: '' }]))
      .toBe('a,b,c,d,e\n,,0,false,');
  });

  it('quotes a value containing a comma', () => {
    expect(toCSV([{ site: 'Ponce, PR' }])).toBe('site\n"Ponce, PR"');
  });

  it('quotes a value containing a newline', () => {
    expect(toCSV([{ note: 'line one\nline two' }])).toBe('note\n"line one\nline two"');
  });

  it('quotes a value containing a quote, and doubles the quote', () => {
    // RFC 4180: the escape for " inside a quoted field is "". Emitting a single
    // quote here would terminate the field early and shift every column after it.
    expect(toCSV([{ note: 'the "main" line' }])).toBe('note\n"the ""main"" line"');
  });

  it('leaves an ordinary value unquoted', () => {
    expect(toCSV([{ a: 'plain', b: 'also-plain' }])).toBe('a,b\nplain,also-plain');
  });

  it('handles a value that needs every escape at once', () => {
    expect(toCSV([{ x: 'a,b"c\nd' }])).toBe('x\n"a,b""c\nd"');
  });

  it('separates rows with a newline and does not trail one', () => {
    const csv = toCSV([{ a: 1 }, { a: 2 }, { a: 3 }]);

    expect(csv).toBe('a\n1\n2\n3');
    expect(csv.endsWith('\n')).toBe(false);
  });
});
