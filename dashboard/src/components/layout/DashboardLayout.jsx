import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import StatsBar from '@/components/StatsBar'
import AiQueryPanel from '@/components/AiQueryPanel'
import { SidebarProvider, useSidebar } from '@/contexts/SidebarContext'
import { useIsMobile } from '@/hooks/use-mobile'
import { Menu } from 'lucide-react'

function Inner() {
  const { collapsed, setCollapsed } = useSidebar()
  const isMobile = useIsMobile()

  const sidebarOpen = isMobile ? !collapsed : true
  const marginLeft = isMobile ? 0 : collapsed ? 56 : 224

  return (
    <div className="flex h-screen bg-slate-950 text-slate-200 overflow-hidden">
      {/* Mobile overlay */}
      {isMobile && !collapsed && (
        <div
          className="fixed inset-0 bg-black/50 z-30"
          onClick={() => setCollapsed(true)}
        />
      )}

      <Sidebar />

      <div
        className="flex flex-col flex-1 min-w-0 transition-all duration-200"
        style={{ marginLeft }}
      >
        {/* Mobile header bar */}
        {isMobile && (
          <div className="flex items-center gap-3 px-3 py-2 border-b border-slate-800 bg-slate-900/80 shrink-0 z-20">
            <button
              onClick={() => setCollapsed(c => !c)}
              className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200"
            >
              <Menu className="h-5 w-5" />
            </button>
            <span className="text-sm font-semibold text-slate-100">AguaYLuz-PR</span>
          </div>
        )}

        <StatsBar />
        <main className="flex-1 min-h-0 overflow-auto">
          <Outlet />
        </main>
      </div>
      <AiQueryPanel />
    </div>
  )
}

export default function DashboardLayout() {
  return (
    <SidebarProvider>
      <Inner />
    </SidebarProvider>
  )
}
