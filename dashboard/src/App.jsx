import { lazy, Suspense } from 'react'
import { Toaster } from '@/components/ui/toaster'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import { BrowserRouter, HashRouter, Route, Routes } from 'react-router-dom'
import { Skeleton } from '@/components/ui/skeleton'
import DashboardLayout from './components/layout/DashboardLayout'
import ScrollToTop from './components/ScrollToTop'

const OFFLINE = import.meta.env.VITE_OFFLINE === '1'
const Router = OFFLINE ? HashRouter : BrowserRouter

// Routes are code-split so the initial bundle stays small (MapLibre and Recharts
// are the heavy chunks, pulled only when their route is visited). The offline
// single-file export inlines these async chunks back into one index.html.
const OverviewPage = lazy(() => import('./pages/OverviewPage'))
const MapPage = lazy(() => import('./pages/MapPage'))
const AssetsPage = lazy(() => import('./pages/AssetsPage'))
const OutagesPage = lazy(() => import('./pages/OutagesPage'))
const MonitoringPage = lazy(() => import('./pages/MonitoringPage'))
const ReviewPage = lazy(() => import('./pages/ReviewPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
const LiveLogsPage = lazy(() => import('./pages/LiveLogsPage'))
const SectorDetailPage = lazy(() => import('./pages/SectorDetailPage'))
const PageNotFound = lazy(() => import('./lib/PageNotFound'))

function PageFallback() {
  return (
    <div className="p-6 space-y-4">
      <Skeleton className="h-8 w-48 rounded" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-lg" />)}
      </div>
    </div>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClientInstance}>
      <Router>
        <ScrollToTop />
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route element={<DashboardLayout />}>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/map" element={<MapPage />} />
              <Route path="/assets" element={<AssetsPage />} />
              <Route path="/outages" element={<OutagesPage />} />
              <Route path="/monitoring" element={<MonitoringPage />} />
              <Route path="/review" element={<ReviewPage />} />
              <Route path="/analytics" element={<AnalyticsPage />} />
              <Route path="/logs" element={<LiveLogsPage />} />
              <Route path="/sector/:sector" element={<SectorDetailPage />} />
              <Route path="*" element={<PageNotFound />} />
            </Route>
          </Routes>
        </Suspense>
      </Router>
      <Toaster />
    </QueryClientProvider>
  )
}

export default App
