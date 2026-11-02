import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, Map, Database, ShieldAlert, Droplets, Leaf, Landmark,
  ClipboardList, BarChart3, ScrollText, SlidersHorizontal, ChevronRight, X,
} from 'lucide-react'
import { useSidebar } from '@/contexts/SidebarContext'
import { useIsMobile } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'
import brandMark from "@/assets/icon-64.png?inline";

// Tabs -> rows -> sub-links. Every routed page appears exactly once.
const NAV_GROUPS = [
  {
    id: 'monitor',
    label: 'Monitor',
    items: [
      { to: '/', end: true, icon: LayoutDashboard, label: 'Overview',
        desc: 'Current status across power, water, wastewater and telecom.' },
      { to: '/map', icon: Map, label: 'Map',
        desc: 'Assets and hazard overlays across Puerto Rico.' },
      { to: '/alerts', icon: ShieldAlert, label: 'Alerts',
        desc: 'Active alerts, service outages and monitoring signals.',
        links: [
          { to: '/outages', label: 'Outages' },
          { to: '/monitoring', label: 'Monitoring' },
        ] },
    ],
  },
  {
    id: 'data',
    label: 'Data',
    items: [
      { to: '/assets', icon: Database, label: 'Assets',
        desc: 'Infrastructure registry with filters and detail.' },
      { to: '/water-disruption', icon: Droplets, label: 'Water & Weather',
        desc: 'Water service validation and National Weather Service hydromet.',
        links: [{ to: '/hydromet', label: 'NWS Hydromet' }] },
      { to: '/environmental-exposure', icon: Leaf, label: 'Environment',
        desc: 'Exposure graph and environmental sources.',
        links: [{ to: '/cave-karst', label: 'Cave & Karst' }] },
      { to: '/regulatory', end: true, icon: Landmark, label: 'Regulatory',
        desc: 'Regulatory records and compliance context.',
        links: [{ to: '/regulatory/review', label: 'Regulatory Review' }] },
    ],
  },
  {
    id: 'tools',
    label: 'Tools',
    items: [
      { to: '/review', icon: ClipboardList, label: 'Review Queue',
        desc: 'Accept, reject or skip records awaiting review.' },
      { to: '/analytics', icon: BarChart3, label: 'Analytics',
        desc: 'Trends and summaries across sectors.' },
      { to: '/logs', icon: ScrollText, label: 'Live Logs',
        desc: 'Streaming backend and ingest logs.' },
      { to: '/system', icon: SlidersHorizontal, label: 'System & Tools',
        desc: 'Integrations, exports and notifications.' },
    ],
  },
]

const inGroup = (group, pathname) => group.items.some(({ to, links = [] }) =>
  [to, ...links.map(l => l.to)].some(p => (p === '/' ? pathname === '/' : pathname === p || pathname.startsWith(`${p}/`))))

const groupFor = (pathname) => (NAV_GROUPS.find(g => inGroup(g, pathname)) ?? NAV_GROUPS[0]).id

// One row, two densities: compact in the desktop panel, EIA-style card on mobile.
function Row({ item, mobile, onNavigate }) {
  const { to, end, icon: Icon, label, desc, links = [] } = item
  return (
    <li className={cn(mobile ? 'flex gap-5 py-6' : 'py-2')}>
      {mobile && (
        <span className="mt-1 flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-2 border-emerald-700/70 text-emerald-700">
          <Icon className="h-6 w-6" />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <NavLink
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) => cn(
            'flex items-center gap-2 font-semibold',
            mobile
              ? 'text-xl text-sky-700'
              : cn('rounded-md px-2 py-1.5 text-sm', isActive
                ? 'bg-sky-500/15 text-sky-400'
                : 'text-slate-300 hover:bg-slate-800/60 hover:text-slate-100'),
          )}
        >
          {!mobile && <Icon className="h-4 w-4 shrink-0" />}
          <span className="truncate">{label}</span>
          {mobile && <ChevronRight className="h-4 w-4 shrink-0" />}
        </NavLink>
        {mobile && <p className="mt-1 text-base text-slate-500">{desc}</p>}
        {links.length > 0 && (
          <ul className={cn(mobile ? 'mt-3 list-disc space-y-2 pl-5 marker:text-slate-800' : 'ml-6 mt-0.5 space-y-0.5')}>
            {links.map(link => (
              <li key={link.to}>
                <NavLink
                  to={link.to}
                  end
                  onClick={onNavigate}
                  className={({ isActive }) => cn(
                    mobile
                      ? cn('text-base', isActive ? 'font-semibold text-sky-800' : 'text-sky-700')
                      : cn('block rounded-md px-2 py-1 text-xs', isActive
                        ? 'bg-sky-500/15 text-sky-400'
                        : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'),
                  )}
                >
                  {link.label}{mobile && ' ›'}
                </NavLink>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  )
}

export default function Sidebar() {
  const { open, setOpen } = useSidebar()
  const isMobile = useIsMobile()
  const { pathname } = useLocation()
  const [tab, setTab] = useState(() => groupFor(pathname))
  const close = () => setOpen(false)

  // Each time the drawer opens, start on the tab that holds the current page.
  useEffect(() => { if (open) setTab(groupFor(pathname)) }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, setOpen])

  if (isMobile) {
    if (!open) return null
    const group = NAV_GROUPS.find(g => g.id === tab) ?? NAV_GROUPS[0]
    return (
      <aside className="fixed inset-0 z-[60] flex flex-col bg-white" aria-label="Navigation">
        <div className="relative shrink-0 bg-slate-900 px-5 pb-6 pt-7">
          <div role="tablist" className="flex gap-6 pr-14">
            {NAV_GROUPS.map(g => (
              <button
                key={g.id}
                role="tab"
                aria-selected={g.id === tab}
                onClick={() => setTab(g.id)}
                className={cn(
                  'border-b-4 pb-1 text-lg',
                  g.id === tab ? 'border-yellow-400 text-white' : 'border-transparent text-slate-300',
                )}
              >
                {g.label}
              </button>
            ))}
          </div>
          <button
            onClick={close}
            aria-label="Close navigation"
            className="absolute right-4 top-4 flex h-11 w-11 items-center justify-center rounded-full bg-sky-500 text-white"
          >
            <X className="h-6 w-6" />
          </button>
        </div>
        <nav aria-label={`${group.label} pages`} className="flex-1 overflow-y-auto px-5">
          <ul className="divide-y divide-slate-200">
            {group.items.map(item => <Row key={item.to} item={item} mobile onNavigate={close} />)}
          </ul>
        </nav>
      </aside>
    )
  }

  return (
    <aside className="fixed left-0 top-0 z-40 flex h-screen w-64 flex-col border-r border-slate-800 bg-slate-900">
      <div className="flex h-14 shrink-0 items-center gap-2.5 border-b border-slate-800 px-3">
        <img src={brandMark} alt="" aria-hidden="true" className="h-6 w-6 shrink-0 rounded-md" />
        <div className="min-w-0">
          <span className="block truncate text-sm font-semibold text-slate-100">AguaYLuz-PR</span>
          <span className="block font-mono text-[10px] uppercase tracking-wider text-slate-500">PR Monitor</span>
        </div>
      </div>
      <nav aria-label="Main" className="flex-1 space-y-4 overflow-y-auto px-2 py-3">
        {NAV_GROUPS.map(g => (
          <section key={g.id}>
            <h2 className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{g.label}</h2>
            <ul>{g.items.map(item => <Row key={item.to} item={item} />)}</ul>
          </section>
        ))}
      </nav>
    </aside>
  )
}
