// Infrastructure-sector metadata: label, icon, accent classes, and the asset values
// that map an asset to a sector. Single source for the Overview sector cards and the
// per-sector detail page.
//
// `types` matches on asset_type — the same field and vocabulary the backend's
// SECTOR_TYPE_MAP (/summary/sectors) counts on, so the card totals and the drilldown
// agree. `subtypes` is the corpus's real asset_subtype vocabulary, used to break a
// sector down on its detail page (asset_type has only 3 values across 8k+ assets,
// so it alone cannot distinguish a reservoir from a canal segment).
import { Zap, Droplets, Trash2, Radio } from 'lucide-react'

export const SECTOR_META = {
  power: {
    label: 'Power', icon: Zap, color: 'text-amber-400',
    border: 'border-amber-500/30', bg: 'bg-amber-500/5',
    types: ['power_plant', 'substation', 'transmission_line', 'generation', 'power'],
    subtypes: ['Substation', 'Transmission Corridor', 'Generation (Water)', 'Generation (Natural Gas)',
      'Generation (Fuel Oil)', 'Generation (Solar PV)', 'Generation (Coal)',
      'Generation (Fuel Oil/Gas)', 'Generation (Solar+Battery)'],
  },
  water: {
    label: 'Water', icon: Droplets, color: 'text-sky-400',
    border: 'border-sky-500/30', bg: 'bg-sky-500/5',
    types: ['water_treatment', 'water_distribution', 'reservoir', 'pump_station', 'water'],
    subtypes: ['waterworks', 'canal_feature', 'stream_gage', 'irrigation_canal', 'reservoir',
      'historic_aqueduct', 'groundwater_well', 'lake', 'pumping_station', 'historic_waterworks',
      'intake_outfall', 'canal_system', 'tide_gauge', 'treatment', 'conduit_alignment'],
  },
  wastewater: {
    label: 'Wastewater', icon: Trash2, color: 'text-emerald-400',
    border: 'border-emerald-500/30', bg: 'bg-emerald-500/5',
    types: ['wastewater_treatment', 'sewage', 'wastewater'],
    subtypes: ['wastewater_treatment'],
  },
  telecom: {
    label: 'Telecom', icon: Radio, color: 'text-violet-400',
    border: 'border-violet-500/30', bg: 'bg-violet-500/5',
    types: ['cell_tower', 'fiber', 'telecom', 'communications'],
    // No telecom assets are ingested today; the sector is declared for the
    // TELECOM_SCADA alert module and renders as "no assets tracked" until one lands.
    subtypes: [],
  },
}
