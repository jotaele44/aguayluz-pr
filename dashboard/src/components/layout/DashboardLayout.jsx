import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import StatsBar from '@/components/StatsBar'
import AiQueryPanel from '@/components/AiQueryPanel'
import { SidebarProvider, useSidebar } from '@/contexts/SidebarContext'

function Inner() {
  const { collapsed } = useSidebar()
  return (
    <div className="flex h-screen bg-slate-950 text-slate-200 overflow-hidden">
      <Sidebar />
      <div className={`flex flex-col flex-1 min-w-0 transition-all duration-200 ${collapsed ? 'ml-14' : 'ml-56'}`}>
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
