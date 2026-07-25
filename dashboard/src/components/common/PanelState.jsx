import { Skeleton } from '@/components/ui/skeleton'
import { AlertTriangle, Database } from 'lucide-react'
import { FederationEmptyState } from '@pr-federation/react'

// Standard async-panel states so every data panel behaves the same: loading
// skeletons, a distinct backend-unreachable state, and an empty state. Pass
// `isError` (e.g. derived from useHealth) so "backend down" doesn't read as
// "no records". Renders `children` only once there is data to show.
export default function PanelState({
  isLoading,
  isError,
  isEmpty,
  rows = 5,
  skeletonClass = 'h-12',
  errorText = 'Backend unreachable — data may be stale.',
  emptyText = 'Nothing to show.',
  children,
}) {
  if (isLoading) {
    return (
      <div className="space-y-1.5 p-2">
        {Array.from({ length: rows }).map((_, i) => (
          <Skeleton key={i} className={`w-full rounded-md ${skeletonClass}`} />
        ))}
      </div>
    )
  }
  if (isError) {
    return (
      <div className="flex h-full min-h-32 flex-col items-center justify-center gap-2 px-4 text-center text-sm text-red-300/80">
        <AlertTriangle className="h-5 w-5" />
        {errorText}
      </div>
    )
  }
  if (isEmpty) {
    // Shared federation empty state (@pr-federation/react) so every data panel's
    // "nothing to show" reads identically across the federation.
    return (
      <FederationEmptyState
        className="min-h-32"
        icon={<Database className="h-5 w-5" />}
        title={emptyText}
      />
    )
  }
  return children
}
