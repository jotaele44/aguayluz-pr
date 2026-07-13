// Infrastructure-sector metadata: label, icon, accent classes, and the asset_type
// substrings that map an asset to a sector. Single source for the Overview sector
// cards and the per-sector detail page.
import { Zap, Droplets, Trash2, Radio } from 'lucide-react'

export const SECTOR_META = {
  power: {
    label: 'Power', icon: Zap, color: 'text-amber-400',
    border: 'border-amber-500/30', bg: 'bg-amber-500/5',
    types: ['power_plant', 'substation', 'transmission_line', 'generation', 'power'],
  },
  water: {
    label: 'Water', icon: Droplets, color: 'text-sky-400',
    border: 'border-sky-500/30', bg: 'bg-sky-500/5',
    types: ['water_treatment', 'water_distribution', 'reservoir', 'pump_station', 'water'],
  },
  wastewater: {
    label: 'Wastewater', icon: Trash2, color: 'text-emerald-400',
    border: 'border-emerald-500/30', bg: 'bg-emerald-500/5',
    types: ['wastewater_treatment', 'sewage', 'wastewater'],
  },
  telecom: {
    label: 'Telecom', icon: Radio, color: 'text-violet-400',
    border: 'border-violet-500/30', bg: 'bg-violet-500/5',
    types: ['cell_tower', 'fiber', 'telecom', 'communications'],
  },
}
