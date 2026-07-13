import MonitoringCharts from '@/components/MonitoringCharts'
import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'

export default function MonitoringPage() {
  return (
    <div className="flex flex-col h-full">
      <PageHeader title="Monitoring" subtitle="Reservoir levels, generation output, and reliability metrics" />
      <div className="flex-1 min-h-0">
        <ErrorBoundary label="Monitoring">
          <MonitoringCharts />
        </ErrorBoundary>
      </div>
    </div>
  )
}
