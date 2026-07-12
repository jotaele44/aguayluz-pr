import { Toaster } from '@/components/ui/toaster'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import { BrowserRouter, HashRouter, Route, Routes } from 'react-router-dom'
import DashboardLayout from './components/layout/DashboardLayout'
import OverviewPage from './pages/OverviewPage'
import MapPage from './pages/MapPage'
import AssetsPage from './pages/AssetsPage'
import OutagesPage from './pages/OutagesPage'
import MonitoringPage from './pages/MonitoringPage'
import ReviewPage from './pages/ReviewPage'
import AnalyticsPage from './pages/AnalyticsPage'
import LiveLogsPage from './pages/LiveLogsPage'
import SectorDetailPage from './pages/SectorDetailPage'
import RepoAnalyzerPage from './pages/RepoAnalyzerPage'
import MycelialAssistantPage from './pages/MycelialAssistantPage'
import PageNotFound from './lib/PageNotFound'
import ScrollToTop from './components/ScrollToTop'

const Router = import.meta.env.VITE_OFFLINE === '1' ? HashRouter : BrowserRouter

function App() {
  return (
    <QueryClientProvider client={queryClientInstance}>
      <Router>
        <ScrollToTop />
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
            <Route path="/mycelial" element={<MycelialAssistantPage />} />
            <Route path="/sector/:sector" element={<SectorDetailPage />} />
            <Route path="/tools/repo-analyzer" element={<RepoAnalyzerPage />} />
            <Route path="*" element={<PageNotFound />} />
          </Route>
        </Routes>
      </Router>
      <Toaster />
    </QueryClientProvider>
  )
}

export default App
