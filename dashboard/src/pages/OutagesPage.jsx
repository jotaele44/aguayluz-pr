import OutagesPanel from '@/components/OutagesPanel'
import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'

export default function OutagesPage() {
  return (
    <div className="flex flex-col h-full">
      <PageHeader title="Outages & Events" subtitle="Service interruptions, restorations, and utility events across Puerto Rico" />
      <div className="flex-1 min-h-0">
        <ErrorBoundary label="Outages">
          <OutagesPanel />
        </ErrorBoundary>
      </div>
    </div>
  )
}
