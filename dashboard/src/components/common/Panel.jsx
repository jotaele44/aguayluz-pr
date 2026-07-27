import { FederationPanel } from '@pr-federation/react'
import { cn } from '@/lib/utils'

// Standard card surface, on the shared federation `.fd-panel` primitive so every
// producer's panels share one surface/border/elevation. Optional uppercase title.
export default function Panel({ title, className, children }) {
  return (
    <FederationPanel className={cn('p-5', className)}>
      {title && (
        <h3 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-400">{title}</h3>
      )}
      {children}
    </FederationPanel>
  )
}
