import { describe, it, expect } from 'vitest';

import {
  CRITICAL_SEVERITY,
  INACTIVE_ALERT_STATUS,
  SEVERITIES,
  alertModuleMeta,
  alertSeverityMeta,
  fmtDate,
  gapBadge,
  isAlertActionable,
  isAlertCritical,
  severityTone,
  statusTone,
  typeMeta,
} from '@/lib/format';

// format.js is mostly lookup tables, and the interesting behaviour is almost all
// in what happens when a key is *not* in the table — those fallbacks decide
// whether an unrecognised value reads as benign, as unknown, or as itself. The
// two exceptions are fmtDate (four branches, only two of which normalise) and
// the alert-actionability pair, which is a deliberate blocklist mirroring the
// backend.

describe('isAlertActionable / isAlertCritical', () => {
  // INACTIVE_ALERT_STATUS is a blocklist, not an allowlist — it mirrors
  // INACTIVE_ALERT_STATUS in server/backend/main.py and _ALERT_INACTIVE_STATUS in
  // scripts/federation_export.py. Inverting it would silently drop every alert
  // whose status the frontend has not heard of, so "active" would stop meaning
  // the same thing in the list, the map, /health and the Hub.

  it('treats only the two retired statuses as inactive', () => {
    expect(INACTIVE_ALERT_STATUS).toEqual(['closed', 'rejected']);
    expect(isAlertActionable({ status: 'closed' })).toBe(false);
    expect(isAlertActionable({ status: 'rejected' })).toBe(false);
  });

  it('counts a status it has never seen as actionable', () => {
    // The blocklist semantics in one assertion: `draft` is not in the list, and a
    // status invented tomorrow will not be either. Both must stay actionable.
    expect(isAlertActionable({ status: 'draft' })).toBe(true);
    expect(isAlertActionable({ status: 'some_future_status' })).toBe(true);
    expect(isAlertActionable({})).toBe(true);
  });

  it('does not throw on a missing alert, and calls it actionable', () => {
    expect(isAlertActionable(undefined)).toBe(true);
    expect(isAlertActionable(null)).toBe(true);
  });

  it('is critical at exactly the life-safety threshold, not above it', () => {
    expect(CRITICAL_SEVERITY).toBe(4); // must match the backend's constant
    expect(isAlertCritical({ severity: CRITICAL_SEVERITY, status: 'open' })).toBe(true);
    expect(isAlertCritical({ severity: CRITICAL_SEVERITY - 1, status: 'open' })).toBe(false);
    expect(isAlertCritical({ severity: 5, status: 'open' })).toBe(true);
  });

  it('requires an integer severity, so a stringified one is not critical', () => {
    // Number.isInteger('4') is false. This is the stricter half of an asymmetry
    // worth knowing about — see the alertSeverityMeta test below, which does
    // resolve '4', because object keys coerce.
    expect(isAlertCritical({ severity: '4', status: 'open' })).toBe(false);
    expect(isAlertCritical({ severity: 4.5, status: 'open' })).toBe(false);
    expect(isAlertCritical({ status: 'open' })).toBe(false);
    expect(isAlertCritical(undefined)).toBe(false);
  });

  it('never calls a retired alert critical however severe it is', () => {
    expect(isAlertCritical({ severity: 5, status: 'closed' })).toBe(false);
    expect(isAlertCritical({ severity: 5, status: 'rejected' })).toBe(false);
  });
});

describe('fmtDate', () => {
  it('renders an em dash for a missing value rather than "Invalid Date"', () => {
    expect(fmtDate(null)).toBe('—');
    expect(fmtDate(undefined)).toBe('—');
    expect(fmtDate('')).toBe('—');
  });

  it('echoes an unparseable value back instead of hiding it', () => {
    expect(fmtDate('not a date')).toBe('not a date');
    expect(fmtDate('2026-13-45')).toBe('2026-13-45');
  });

  it('normalises a datetime to UTC, minute precision', () => {
    expect(fmtDate('2026-03-15T08:30:00Z')).toBe('2026-03-15 08:30');
  });

  it('shifts an offset datetime into UTC — including across a day boundary', () => {
    // The time branch round-trips through toISOString(), so an AST timestamp is
    // re-expressed in UTC. At 20:00-04:00 that moves the *date* forward too.
    expect(fmtDate('2026-03-15T08:30:00-04:00')).toBe('2026-03-15 12:30');
    expect(fmtDate('2026-03-15T20:00:00-04:00')).toBe('2026-03-16 00:00');
  });

  it('leaves a date-only value untouched — it is sliced, never converted', () => {
    // The asymmetry that matters: the date-only branch is a pure string slice, so
    // it never shifts, while the branch above always does.
    expect(fmtDate('2026-03-15')).toBe('2026-03-15');
    expect(fmtDate('2026-01-01')).toBe('2026-01-01');
  });

  it('does not zero-pad a loosely written date — proving the slice is a slice', () => {
    // A well-formed date survives toISOString() unchanged, so the two assertions
    // above pass just as happily against an implementation that normalises the
    // date-only branch as well. This one cannot: toISOString() always yields a
    // zero-padded ten-character date, in any timezone, so "2026-3-5" is a result
    // only a genuine string slice can produce.
    expect(fmtDate('2026-3-5')).toBe('2026-3-5');
  });
});

describe('severityTone', () => {
  // The review queue's own filter vocabulary. scripts/federation_export.py writes
  // "warn" for review_status=needs_review and "block" otherwise, so these are the
  // values that actually reach the UI — all 5,846 records in outputs/review_queue.json
  // are "warn" today. They must not all collapse into the fallback.
  const REVIEW_SEVERITIES = SEVERITIES.filter((s) => s !== 'all');

  it('gives every filterable severity a tone of its own', () => {
    const tones = REVIEW_SEVERITIES.map(severityTone);

    expect(new Set(tones).size).toBe(REVIEW_SEVERITIES.length);
  });

  it('distinguishes a blocking record from a warning one', () => {
    // The whole point of the indicator. Before block/warn were added to the map
    // both returned the slate fallback and this assertion failed.
    expect(severityTone('block')).not.toBe(severityTone('warn'));
    expect(severityTone('block')).not.toBe(severityTone(undefined));
    expect(severityTone('warn')).not.toBe(severityTone(undefined));
  });

  it('keeps the descriptive scale mapped as well', () => {
    expect(severityTone('critical')).not.toBe(severityTone('high'));
    expect(severityTone('medium')).not.toBe(severityTone('low'));
  });

  it('falls back to slate for an unknown severity', () => {
    expect(severityTone('not-a-severity')).toBe('text-slate-400');
  });
});

describe('statusTone', () => {
  // Colour comes from the shared federation status tokens, not from local hues:
  // federationTone() returns { className: 'fd-status', 'data-status': <role> } and
  // statusTone re-merges an extra class through cn(). Assert the role *value* —
  // a className is always present, so checking for one proves nothing.
  it.each([
    ['active', 'success'],
    ['inactive', 'neutral'],
    ['damaged', 'danger'],
    ['planned', 'warning'],
  ])('maps the %s status to the %s role', (status, role) => {
    expect(statusTone(status)['data-status']).toBe(role);
  });

  it('keeps the four statuses on distinct roles', () => {
    const roles = ['active', 'inactive', 'damaged', 'planned'].map((s) => statusTone(s)['data-status']);

    expect(new Set(roles).size).toBe(4);
  });

  it('falls back to neutral, distinguishably', () => {
    expect(statusTone('not-a-status')['data-status']).toBe('neutral');
    expect(statusTone(undefined)['data-status']).toBe('neutral');
    expect(statusTone('not-a-status')['data-status']).not.toBe(statusTone('damaged')['data-status']);
  });

  it('merges an extra class without dropping the federation one', () => {
    const { className } = statusTone('active', 'mt-2');

    expect(className).toContain('fd-status');
    expect(className).toContain('mt-2');
  });
});

describe('lookup fallbacks', () => {
  it('typeMeta echoes an unknown asset type as its own label', () => {
    // Better than a generic "Other": an unmapped type stays legible in the UI and
    // is obvious to whoever has to add it.
    expect(typeMeta('geothermal').label).toBe('geothermal');
    expect(typeMeta('power').label).toBe('Power');
    expect(typeMeta(undefined).label).toBe('—');
  });

  it('alertModuleMeta echoes an unknown module id, because the list is server-driven', () => {
    // The module list the UI filters on comes from GET /alerts/facets, so a newly
    // activated module must render without a frontend change.
    expect(alertModuleMeta('NEW_SECTOR').label).toBe('NEW_SECTOR');
    expect(alertModuleMeta('HYDRO_OPS').label).toBe('Hydro ops');
    expect(alertModuleMeta(undefined).label).toBe('Unclassified');
  });

  it('alertSeverityMeta resolves a stringified severity but not an out-of-range one', () => {
    // The looser half of the asymmetry flagged above: object keys coerce, so '4'
    // renders as "Severe" even though isAlertCritical({severity:'4'}) is false.
    expect(alertSeverityMeta(4).label).toBe('Severe');
    expect(alertSeverityMeta('4').label).toBe('Severe');
    expect(alertSeverityMeta(6).label).toBe('—');
    expect(alertSeverityMeta(undefined).label).toBe('—');
  });

  it('gapBadge treats an unknown gap status as "none" — the most reassuring one', () => {
    // Worth stating out loud: this fallback fails *open*. An evidence gap the UI
    // does not recognise renders the same green as no gap at all.
    expect(gapBadge('unrecognised')).toBe(gapBadge('none'));
    expect(gapBadge('blocking')).not.toBe(gapBadge('none'));
  });
});
