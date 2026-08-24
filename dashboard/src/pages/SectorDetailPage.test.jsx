import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import SectorDetailPage from '@/pages/SectorDetailPage';

// This page takes its sector straight from the URL, which makes it the one place
// in the dashboard where a stranger picks the lookup key. `/sector/__proto__`
// used to resolve SECTOR_META to Object.prototype — truthy, so the "Unknown
// sector" guard passed it through — and then threw on meta.types.some(...),
// blanking the page. These tests pin that a hand-typed path cannot do that.

vi.mock('@/lib/hooks', () => ({
  useAssets: () => ({ data: [], isLoading: false }),
  useEvents: () => ({ data: [], isLoading: false }),
  useSummarySectors: () => ({ data: {} }),
}));

const renderAt = (sector) =>
  render(
    <MemoryRouter initialEntries={[`/sector/${sector}`]}>
      <Routes>
        <Route path="/sector/:sector" element={<SectorDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );

// A crash inside a React render surfaces as a thrown error out of render(), but
// React also logs it. Silence that so a passing run is not full of red noise.
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});

describe('SectorDetailPage — URL-supplied sector', () => {
  it('renders a known sector', () => {
    renderAt('power');

    expect(screen.getByText(/Power Infrastructure/i)).toBeInTheDocument();
  });

  it('shows the unknown-sector message for an ordinary bad path', () => {
    renderAt('not-a-sector');

    expect(screen.getByText(/Unknown sector/i)).toBeInTheDocument();
  });

  it.each(['__proto__', 'constructor', 'toString', 'valueOf', 'hasOwnProperty'])(
    'treats /sector/%s as unknown rather than crashing',
    (sector) => {
      // Before the fix this threw:
      //   TypeError: Cannot read properties of undefined (reading 'some')
      // because Object.prototype is truthy and slipped past the !meta guard.
      expect(() => renderAt(sector)).not.toThrow();
      expect(screen.getByText(/Unknown sector/i)).toBeInTheDocument();
    },
  );

  it('does not render sector chrome for an inherited key', () => {
    // Distinctness: "did not crash" is not the same as "handled correctly".
    // The page must show the guard message, not a half-built sector view.
    renderAt('__proto__');

    expect(screen.queryByText(/Infrastructure$/)).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
