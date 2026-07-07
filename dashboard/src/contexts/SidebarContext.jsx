import { createContext, useContext, useState } from 'react'

const SidebarCtx = createContext({ collapsed: false, setCollapsed: () => {} })

export const useSidebar = () => useContext(SidebarCtx)

export function SidebarProvider({ children }) {
  const [collapsed, setCollapsed] = useState(false)
  return <SidebarCtx.Provider value={{ collapsed, setCollapsed }}>{children}</SidebarCtx.Provider>
}
