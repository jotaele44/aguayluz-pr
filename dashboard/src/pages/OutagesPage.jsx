import OutagesPanel from '@/components/OutagesPanel'
import ErrorBoundary from '@/components/ErrorBoundary'

export default function OutagesPage() {
  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-slate-800 shrink-0">
        <h1 className="text-lg font-semibold text-slate-100">Outages & Events</h1>
        <p className="text-xs text-slate-500 mt-0.5">Service interruptions, restorations, and utility events across Puerto Rico</p>
      </div>
      <div className="flex-1 min-h-0">
        <ErrorBoundary label="Outages">
          <OutagesPanel />
        </ErrorBoundary>
      </div>
    </div>
  )
}
