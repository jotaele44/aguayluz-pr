import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'
import WaterMonitoringConsole from '@/components/WaterMonitoringConsole'

export default function MonitoringPage() {
  return (
    <div className="flex flex-col h-full min-h-0">
      <PageHeader
        title="Puerto Rico Water Monitoring"
        subtitle="Rivers, reservoirs, rainfall, groundwater, coastal water, watersheds, extraction, and water quality — provenance-first and fail-closed"
      />
      <ErrorBoundary label="Water monitoring">
        <WaterMonitoringConsole />
      </ErrorBoundary>
    </div>
  )
}
