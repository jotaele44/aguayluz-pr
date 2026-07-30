import MonitoringCharts from '@/components/MonitoringCharts'
import IncidentOperationsConsole from '@/components/IncidentOperationsConsole'
import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'

export default function MonitoringPage() {
  return (
    <div className="flex flex-col h-full">
      <PageHeader title="Monitoring" subtitle="Reservoir, groundwater, and coastal water levels — USGS NWIS and NOAA CO-OPS daily series" />
      <div className="flex-1 min-h-0 overflow-auto">
        <ErrorBoundary label="Monitoring">
          <MonitoringCharts />
          <IncidentOperationsConsole />
        </ErrorBoundary>
      </div>
    </div>
  )
}
