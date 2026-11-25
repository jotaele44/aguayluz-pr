import { useEffect } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

// Nothing else imports Sidebar.jsx under test, so a merge that left it
// unparseable (c848ac05) passed the whole suite and was caught only by lint and
// build. These tests render it, so that breakage, or a silently dropped page,
// fails `npm run test` too.
//
// Two jsdom details shape the helper below:
// - jsdom has no window.matchMedia, which useIsMobile() calls in an effect, so
//   it is stubbed along with the width the hook reads on first render.
// - The /ionosphere link depends on VITE_IONOSPHERE_PREVIEW, which NAV_GROUPS
//   reads once, when the module loads. Each render therefore resets the module
//   registry and imports Sidebar and SidebarContext afresh, together, so both
//   see the same context object. React and the router are not reset.

const PREVIEW_LABEL = 'Space weather / Clima espacial'

// Every page the navigation is expected to reach with the preview flag off.
const CORE_ROUTES = [
  '/', '/map', '/alerts', '/outages', '/monitoring', '/assets',
  '/water-disruption', '/hydromet', '/aquifer-bands', '/water-use', '/hydro-inventory',
  '/environmental-exposure', '/cave-karst', '/regulatory', '/regulatory/review',
  '/review', '/analytics', '/source-intelligence', '/logs', '/system',
]

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

async function renderSidebar({ path = '/', flag = false, width = 1280, open = false } = {}) {
  vi.resetModules()
  if (flag) vi.stubEnv('VITE_IONOSPHERE_PREVIEW', '1')
  vi.stubGlobal('innerWidth', width)
  vi.stubGlobal('matchMedia', () => ({
    matches: width < 768,
    addEventListener() {},
    removeEventListener() {},
  }))
  const { default: Sidebar } = await import('./Sidebar')
  const { SidebarProvider, useSidebar } = await import('@/contexts/SidebarContext')

  // The drawer starts closed and only the context can open it.
  function OpenDrawer() {
    const { setOpen } = useSidebar()
    useEffect(() => { setOpen(true) }, [setOpen])
    return null
  }

  return render(
    <MemoryRouter initialEntries={[path]}>
      <SidebarProvider>
        {open && <OpenDrawer />}
        <Sidebar />
      </SidebarProvider>
    </MemoryRouter>,
  )
}

const linkHrefs = (nav) => within(nav).getAllByRole('link').map((a) => a.getAttribute('href'))

describe('Sidebar on desktop', () => {
  it('renders the grouped navigation', async () => {
    await renderSidebar()

    const nav = screen.getByRole('navigation', { name: 'Main' })
    const headings = within(nav).getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings).toEqual(['Monitor', 'Data', 'Tools'])
    expect(screen.getByText('AguaYLuz-PR')).toBeInTheDocument()
  })

  it('links every page, each once', async () => {
    await renderSidebar()

    const hrefs = linkHrefs(screen.getByRole('navigation', { name: 'Main' }))
    const repeated = hrefs.filter((href, i) => hrefs.indexOf(href) !== i)
    expect(repeated).toEqual([])
    expect(hrefs).toEqual(expect.arrayContaining(CORE_ROUTES))
  })

  it('marks the page being viewed', async () => {
    await renderSidebar({ path: '/hydromet' })

    expect(screen.getByRole('link', { name: 'NWS Hydromet' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current')
  })

  it('leaves the ionosphere preview out while its flag is off', async () => {
    await renderSidebar()

    expect(screen.queryByRole('link', { name: PREVIEW_LABEL })).not.toBeInTheDocument()
    expect(linkHrefs(screen.getByRole('navigation', { name: 'Main' }))).not.toContain('/ionosphere')
  })

  it('lists the ionosphere preview after NWS Hydromet while its flag is on', async () => {
    await renderSidebar({ flag: true })

    const preview = screen.getByRole('link', { name: PREVIEW_LABEL })
    const hydromet = screen.getByRole('link', { name: 'NWS Hydromet' })
    expect(preview).toHaveAttribute('href', '/ionosphere')
    expect(preview.closest('ul')).toBe(hydromet.closest('ul'))
    expect(hydromet.compareDocumentPosition(preview) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe('Sidebar on mobile', () => {
  it('renders nothing while the drawer is closed', async () => {
    const { container } = await renderSidebar({ width: 500 })

    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByRole('complementary', { name: 'Navigation' })).not.toBeInTheDocument()
  })

  it('opens as tabs, starting on the tab that holds the current page', async () => {
    await renderSidebar({ path: '/hydromet', width: 500, open: true })

    const tabs = within(await screen.findByRole('tablist')).getAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['Monitor', 'Data', 'Tools'])
    expect(screen.getByRole('tab', { name: 'Data' })).toHaveAttribute('aria-selected', 'true')

    const dataPages = screen.getByRole('navigation', { name: 'Data pages' })
    expect(within(dataPages).getByRole('link', { name: /^Water & Weather/ })).toBeInTheDocument()
    expect(within(dataPages).getByRole('link', { name: /^NWS Hydromet/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: 'Tools' }))

    expect(screen.getByRole('tab', { name: 'Tools' })).toHaveAttribute('aria-selected', 'true')
    const toolsPages = screen.getByRole('navigation', { name: 'Tools pages' })
    expect(within(toolsPages).getByRole('link', { name: /^Review Queue/ })).toBeInTheDocument()
  })

  it.each([
    ['the close button', () => fireEvent.click(screen.getByRole('button', { name: 'Close navigation' }))],
    ['the Escape key', () => fireEvent.keyDown(window, { key: 'Escape' })],
  ])('closes with %s', async (_name, close) => {
    await renderSidebar({ width: 500, open: true })
    expect(await screen.findByRole('complementary', { name: 'Navigation' })).toBeInTheDocument()

    close()

    expect(screen.queryByRole('complementary', { name: 'Navigation' })).not.toBeInTheDocument()
  })
})
