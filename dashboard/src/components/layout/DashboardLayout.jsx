import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import StatsBar from '@/components/StatsBar'
import AiQueryPanel from '@/components/AiQueryPanel'
import { SidebarProvider, useSidebar } from '@/contexts/SidebarContext'
import { useIsMobile } from '@/hooks/use-mobile'
import { Menu } from 'lucide-react'
import brandMark from "@/assets/icon-64.png?inline";

function Inner() {
  const { setOpen } = useSidebar()
  const isMobile = useIsMobile()

  const marginLeft = isMobile ? 0 : 256

  return (
    <div className="flex h-screen bg-slate-950 text-slate-200 overflow-hidden">
      <Sidebar />

      <div
        className="flex flex-col flex-1 min-w-0 transition-all duration-200"
        style={{ marginLeft }}
      >
        {/* Mobile header bar */}
        {isMobile && (
          <div className="flex items-center gap-3 px-3 py-2 border-b border-slate-800 bg-slate-900/80 shrink-0 z-20">
            <button
              onClick={() => setOpen(true)}
              aria-label="Open navigation"
              className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200"
            >
              <Menu className="h-5 w-5" />
            </button>
            <img src={brandMark} alt="" aria-hidden="true" className="h-6 w-6 rounded-md" />
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
