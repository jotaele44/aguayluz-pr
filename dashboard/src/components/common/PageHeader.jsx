// Standard page header: title + optional subtitle, with optional right-aligned
// actions (filters, buttons). Replaces the header block copy-pasted across pages.
export default function PageHeader({ title, subtitle, children }) {
  return (
    <div className="px-6 py-4 border-b border-slate-800 shrink-0 flex items-center gap-4 flex-wrap">
      <div className="min-w-0">
        <h1 className="text-lg font-semibold text-slate-100">{title}</h1>
        {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
      </div>
      {children && <div className="flex items-center gap-2 ml-auto">{children}</div>}
    </div>
  )
}
