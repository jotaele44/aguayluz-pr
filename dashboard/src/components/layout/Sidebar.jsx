import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Map, Database, Zap, Activity, ClipboardList,
  BarChart3, ScrollText, GitBranch, Droplets, ChevronLeft, ChevronRight, Sprout,
} from 'lucide-react'
import { useHealth } from '@/lib/hooks'
import { useSidebar } from '@/contexts/SidebarContext'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Overview', end: true },
  { to: '/map', icon: Map, label: 'Map' },
  { to: '/assets', icon: Database, label: 'Assets' },
  { to: '/outages', icon: Zap, label: 'Outages' },
  { to: '/monitoring', icon: Activity, label: 'Monitoring' },
  { to: '/review', icon: ClipboardList, label: 'Review Queue' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/logs', icon: ScrollText, label: 'Live Logs' },
  { to: '/mycelial', icon: Sprout, label: 'Mycelial Assistant' },
  { to: '/tools/repo-analyzer', icon: GitBranch, label: 'Repo Analyzer' },
]

export default function Sidebar() {
  const { collapsed, setCollapsed } = useSidebar()
  const { data: health } = useHealth()
  const up = health?.status === 'ok'

  return (
    <aside className={cn(
      'fixed left-0 top-0 h-screen bg-slate-900 border-r border-slate-800 flex flex-col z-40 transition-all duration-200',
      collapsed ? 'w-14' : 'w-56',
    )}>
      <div className="h-14 flex items-center gap-2.5 px-3 border-b border-slate-800 shrink-0">
        <Droplets className="h-5 w-5 text-sky-400 shrink-0" />
        {!collapsed && (
          <div className="min-w-0">
            <span className="block text-sm font-semibold text-slate-100 truncate">AguaYLuz-PR</span>
            <span className="block text-[10px] text-slate-500 font-mono uppercase tracking-wider">PR Monitor</span>
          </div>
        )}
        <button
          onClick={() => setCollapsed(c => !c)}
          className="ml-auto p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 shrink-0"
        >
          {collapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
        {NAV.map(({ to, icon: Icon, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) => cn(
              'flex items-center gap-3 px-2 py-2 rounded-md text-sm font-medium transition-colors',
              isActive
                ? 'bg-sky-500/15 text-sky-400'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60',
            )}
            title={collapsed ? label : undefined}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {!collapsed && <span className="truncate">{label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="p-3 border-t border-slate-800">
        <div className="flex items-center gap-2 text-xs text-slate-500 font-mono">
          <span className={cn(
            'w-1.5 h-1.5 rounded-full shrink-0',
            up ? 'bg-emerald-400 animate-pulse' : 'bg-red-400',
          )} />
          {!collapsed && (up ? 'Backend online' : 'Backend down')}
        </div>
      </div>
    </aside>
  )
}
