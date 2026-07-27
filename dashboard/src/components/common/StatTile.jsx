import { FederationStatCard } from '@pr-federation/react'

// KPI tile. Renders on the shared federation design system (`.fd-stat-card` from
// @pr-federation/react/styles.css) so surface, radius, and label treatment match the
// hub and the other producers. The local call signature is kept — `icon` is a
// component, `valueClass` a Tailwind tone — so no caller had to change to adopt it.
export default function StatTile({ icon: Icon, label, value, valueClass = 'text-slate-100', sub }) {
  return (
    <FederationStatCard
      label={label}
      icon={Icon ? <Icon /> : undefined}
      alert={valueClass.includes('red')}
      value={<span className={`font-mono ${valueClass}`}>{value}</span>}
      sub={sub}
    />
  )
}
