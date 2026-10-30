import { createContext, useContext, useState } from 'react'

// `open` only matters on mobile, where navigation is a full-screen drawer.
// The desktop panel is always visible.
const SidebarCtx = createContext({ open: false, setOpen: () => {} })

export const useSidebar = () => useContext(SidebarCtx)

export function SidebarProvider({ children }) {
  const [open, setOpen] = useState(false)
  return <SidebarCtx.Provider value={{ open, setOpen }}>{children}</SidebarCtx.Provider>
}
