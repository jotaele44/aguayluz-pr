import { createContext, useContext, useState } from 'react'

const SidebarCtx = createContext({ collapsed: false, setCollapsed: () => {} })

export const useSidebar = () => useContext(SidebarCtx)

export function SidebarProvider({ children }) {
  const [collapsed, setCollapsed] = useState(() => (
    typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches
  ))
  return <SidebarCtx.Provider value={{ collapsed, setCollapsed }}>{children}</SidebarCtx.Provider>
}
