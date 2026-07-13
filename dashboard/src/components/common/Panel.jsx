import { cn } from '@/lib/utils'

// Standard card surface used throughout the dashboard. Optional uppercase title.
export default function Panel({ title, className, children }) {
  return (
    <div className={cn('bg-slate-900 border border-slate-800 rounded-lg p-5', className)}>
      {title && (
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4">{title}</h3>
      )}
      {children}
    </div>
  )
}
