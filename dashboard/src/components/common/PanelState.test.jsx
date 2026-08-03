import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import PanelState from '@/components/common/PanelState';

// The first component test in this dashboard. Beyond covering PanelState, it is
// what proves the jsdom half of the harness actually works — the lib tests
// alongside it would pass with testing-library entirely absent.
//
// PanelState is four mutually exclusive branches guarding every data panel in
// the app, and the ordering between them is a product decision, not an
// implementation detail: "backend unreachable" must never render as "nothing to
// show", or an outage looks like a quiet day.

const CHILD = <p>real content</p>;
const skeletonCount = (container) => container.querySelectorAll('.animate-pulse').length;

describe('PanelState — one branch at a time', () => {
  it('renders children when nothing is loading, failing or empty', () => {
    render(<PanelState>{CHILD}</PanelState>);

    expect(screen.getByText('real content')).toBeInTheDocument();
  });

  it('renders skeletons while loading, and not the children', () => {
    const { container } = render(<PanelState isLoading>{CHILD}</PanelState>);

    expect(skeletonCount(container)).toBe(5); // the documented default
    expect(screen.queryByText('real content')).not.toBeInTheDocument();
  });

  it('renders the error message, and not the children', () => {
    render(<PanelState isError>{CHILD}</PanelState>);

    expect(screen.getByText(/backend unreachable/i)).toBeInTheDocument();
    expect(screen.queryByText('real content')).not.toBeInTheDocument();
  });

  it('renders the empty message, and not the children', () => {
    render(<PanelState isEmpty>{CHILD}</PanelState>);

    expect(screen.getByText('Nothing to show.')).toBeInTheDocument();
    expect(screen.queryByText('real content')).not.toBeInTheDocument();
  });
});

describe('PanelState — precedence', () => {
  // The branches are checked in order, so the only way to pin the ordering is to
  // assert what wins when more than one flag is set. In practice they overlap
  // constantly: a failed query is both isError and (vacuously) isEmpty.

  it('shows loading over everything else', () => {
    const { container } = render(
      <PanelState isLoading isError isEmpty>{CHILD}</PanelState>,
    );

    expect(skeletonCount(container)).toBe(5);
    expect(screen.queryByText(/backend unreachable/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Nothing to show.')).not.toBeInTheDocument();
  });

  it('shows the error over the empty state — an outage is not an empty result', () => {
    // This is the assertion the component's own comment exists for. A failed
    // fetch leaves the list empty too, so if isEmpty won here every backend
    // outage in the app would render as "Nothing to show."
    render(<PanelState isError isEmpty>{CHILD}</PanelState>);

    expect(screen.getByText(/backend unreachable/i)).toBeInTheDocument();
    expect(screen.queryByText('Nothing to show.')).not.toBeInTheDocument();
  });

  it('shows the empty state over the children', () => {
    render(<PanelState isEmpty>{CHILD}</PanelState>);

    expect(screen.getByText('Nothing to show.')).toBeInTheDocument();
    expect(screen.queryByText('real content')).not.toBeInTheDocument();
  });

  it('keeps the error and empty states visually distinct, not just textually', () => {
    // Different copy is not enough — they must not be the same element with a
    // swapped string, or a panel that renders one while meaning the other is
    // indistinguishable to anyone skimming.
    const { container: errored } = render(<PanelState isError />);
    const { container: empty } = render(<PanelState isEmpty />);

    expect(errored.firstChild.className).not.toBe(empty.firstChild.className);
    expect(empty.querySelector('[role="status"]')).not.toBeNull();
  });
});

describe('PanelState — props', () => {
  it('renders as many skeletons as asked for', () => {
    const { container } = render(<PanelState isLoading rows={3} />);

    expect(skeletonCount(container)).toBe(3);
  });

  it('renders no skeletons for rows={0} rather than falling back to the default', () => {
    // `rows = 5` is a default-parameter, so it applies to undefined but not to 0.
    const { container } = render(<PanelState isLoading rows={0} />);

    expect(skeletonCount(container)).toBe(0);
  });

  it('applies a custom skeleton class to every skeleton', () => {
    const { container } = render(<PanelState isLoading rows={2} skeletonClass="h-24" />);
    const skeletons = [...container.querySelectorAll('.animate-pulse')];

    expect(skeletons).toHaveLength(2);
    expect(skeletons.every((s) => s.className.includes('h-24'))).toBe(true);
  });

  it('overrides the error and empty copy when given', () => {
    render(<PanelState isError errorText="Alerts feed is down." />);
    expect(screen.getByText('Alerts feed is down.')).toBeInTheDocument();
    expect(screen.queryByText(/backend unreachable/i)).not.toBeInTheDocument();

    render(<PanelState isEmpty emptyText="No alerts in this window." />);
    expect(screen.getByText('No alerts in this window.')).toBeInTheDocument();
    expect(screen.queryByText('Nothing to show.')).not.toBeInTheDocument();
  });

  it('renders nothing at all when idle with no children', () => {
    const { container } = render(<PanelState />);

    expect(container).toBeEmptyDOMElement();
  });
});
