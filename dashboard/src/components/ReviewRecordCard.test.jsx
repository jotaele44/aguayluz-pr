import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';

import ReviewRecordCard from '@/components/ReviewRecordCard';
import { severityTone } from '@/lib/format';

// The binding test for the severity indicator. src/lib/format.test.js proves
// severityTone() returns a different class per severity; that is necessary but
// not sufficient, because it says nothing about whether this component still
// calls it. Deleting the severityTone(r.severity) calls below, or freezing them
// to a constant, would leave every one of those lookup-table assertions green
// while the indicator went dead in exactly the way this PR is fixing.
//
// So: render a real record shape and assert the tone reaches the DOM, and that
// two records of different severity do not look the same.

const record = (over = {}) => ({
  record_ref: 'PRASA-1234',
  reason: 'upstream review_status=needs_review (evidence_tier=T2)',
  severity: 'warn',
  ...over,
});

// The severity appears on two elements — the warning icon and the uppercase
// label — and both must carry the tone, or the indicator is half dead.
const toneCarriers = (container) => [
  container.querySelector('svg'),
  [...container.querySelectorAll('span')].find((s) => s.className.includes('uppercase')),
];

describe('ReviewRecordCard severity binding', () => {
  it.each(['block', 'warn', 'info'])('puts the %s tone on the icon and the label', (severity) => {
    const { container } = render(<ReviewRecordCard record={record({ severity })} />);
    const expected = severityTone(severity);

    for (const el of toneCarriers(container)) {
      expect(el, `no element carried the ${severity} tone`).not.toBeNull();
      expect(el.className.baseVal ?? el.className).toContain(expected);
    }
  });

  it('renders a blocking record differently from a warning one', () => {
    // The user-visible claim this PR makes. Both severities reach the UI from
    // scripts/federation_export.py, and before the fix both rendered the same
    // slate class — this assertion failed then and passes now.
    const classesFor = (severity) => {
      const { container } = render(<ReviewRecordCard record={record({ severity })} />);
      return toneCarriers(container).map((el) => el.className.baseVal ?? el.className);
    };

    const [blockIcon, blockLabel] = classesFor('block');
    const [warnIcon, warnLabel] = classesFor('warn');

    expect(blockIcon).not.toBe(warnIcon);
    expect(blockLabel).not.toBe(warnLabel);
  });

  it('still renders a record whose severity it does not recognise', () => {
    // The fallback must degrade to a grey chip, not to a crash — severity is
    // server-supplied and the vocabulary can grow.
    const { container, getByText } = render(
      <ReviewRecordCard record={record({ severity: 'catastrophic' })} />,
    );

    expect(getByText('catastrophic')).toBeInTheDocument();
    const [, label] = toneCarriers(container);
    expect(label.className).toContain(severityTone('catastrophic'));
  });

  it('labels a record with no severity as "review" rather than rendering blank', () => {
    const { getByText } = render(<ReviewRecordCard record={record({ severity: undefined })} />);

    expect(getByText('review')).toBeInTheDocument();
  });

  it('renders the reason, the ref and the evidence tier', () => {
    const { getByText } = render(
      <ReviewRecordCard record={record({ evidence_tier: 'T1', confidence: 82 })} />,
    );

    expect(getByText('PRASA-1234')).toBeInTheDocument();
    expect(getByText(/upstream review_status/)).toBeInTheDocument();
    expect(getByText('T1')).toBeInTheDocument();
    expect(getByText('conf 82')).toBeInTheDocument();
  });

  it('falls back to a placeholder when the record carries no reason', () => {
    const { getByText } = render(<ReviewRecordCard record={record({ reason: '' })} />);

    expect(getByText('No review reason provided.')).toBeInTheDocument();
  });

  it('omits the confidence chip for confidence 0 only when it is absent', () => {
    // `r.confidence != null`, so a genuine score of 0 must still render — it is a
    // measurement, not a missing value.
    const { getByText } = render(<ReviewRecordCard record={record({ confidence: 0 })} />);

    expect(getByText('conf 0')).toBeInTheDocument();
  });
});
