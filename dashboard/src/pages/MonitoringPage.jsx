import MonitoringCharts from '@/components/MonitoringCharts'
import ErrorBoundary from '@/components/ErrorBoundary'

export default function MonitoringPage() {
  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-slate-800 shrink-0">
        <h1 className="text-lg font-semibold text-slate-100">Monitoring</h1>
        <p className="text-xs text-slate-500 mt-0.5">Reservoir levels, generation output, and reliability metrics</p>
      </div>
      <div className="flex-1 min-h-0">
        <ErrorBoundary label="Monitoring">
          <MonitoringCharts />
        </ErrorBoundary>
      </div>
    </div>
  )
}
