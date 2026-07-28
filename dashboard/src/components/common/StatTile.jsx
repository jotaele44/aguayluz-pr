import { FederationStatCard } from '@pr-federation/react'

// KPI tile on the shared federation design system (`.fd-stat-card`), so surface,
// radius, and label treatment match the hub and the other producers.
//
// `tone` is a canonical federation status role, not a Tailwind class. That
// replaces the previous `valueClass` escape hatch, which smuggled palette
// literals through a nested span and inferred `alert` by sniffing the class
// string for "red". The value tint and its monospace figures now come from
// --fd-tone-*/--fd-font-mono in the package CSS, so both follow the theme.
export default function StatTile({ icon: Icon, label, value, tone, sub }) {
  return (
    <FederationStatCard
      label={label}
      icon={Icon ? <Icon /> : undefined}
      alert={tone === 'danger'}
      value={value}
      tone={tone}
      sub={sub}
    />
  )
}
