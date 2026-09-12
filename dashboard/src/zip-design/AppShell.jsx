import { Suspense } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { NAV } from '../components/layout/Sidebar'
import StatsBar from '../components/StatsBar'
import ReadFailureBoundary from '../components/ReadFailureBoundary'
import AiQueryPanel from '../components/AiQueryPanel'
import { SidebarProvider } from '../contexts/SidebarContext'
import styles from './AppShell.module.css'

function Navigation({ compact = false }) {
  return (compact ? NAV.slice(0, 5) : NAV).map(({ to, label, icon: Icon, end }) =>
    <NavLink key={to} to={to} end={end} className={({ isActive }) => `${styles.navLink} ${isActive ? styles.navLinkActive : ''} ${compact ? styles.compactNavLink : ''}`}>
      <Icon size={compact ? 20 : 17} aria-hidden="true" /><span>{label}</span>
    </NavLink>)
}
export default function AppShell() {
  const { pathname } = useLocation()
  return <SidebarProvider><div className={`zip-surface ${styles.shell}`}>
    <aside className={styles.sidebar}>
      <div className={styles.brandRow}><div className={styles.brandCopy}><strong>AguaYLuz</strong><span>Puerto Rico utilities</span></div></div>
      <nav className={styles.nav} aria-label="Main navigation"><div className={styles.navGroup}><span className={styles.navLabel}>Operations & intelligence</span><Navigation /></div></nav>
      <div className={styles.sidebarFooter}>Water · power · outage intelligence</div>
    </aside>
    <div className={styles.workspace}>
      <header className={styles.topbar}><div className={styles.topbarTitle}><strong>AguaYLuz</strong><span className={styles.topbarSub}>Water · power · outage intelligence</span></div></header>
      <details className="zip-mobile-menu"><summary>All workflows</summary><nav aria-label="All mobile workflows"><Navigation /></nav></details>
      <ReadFailureBoundary><StatsBar /><main className={styles.main}><Suspense key={pathname} fallback={<p role="status" className="p-6 text-slate-400">Loading view…</p>}><Outlet /></Suspense></main></ReadFailureBoundary>
      <nav className={styles.bottomNav} aria-label="Mobile navigation"><Navigation compact /></nav>
    </div><AiQueryPanel />
  </div></SidebarProvider>
}
