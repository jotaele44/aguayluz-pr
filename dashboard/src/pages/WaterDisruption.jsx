export default function WaterDisruption() {
  return (
    <main className="mx-auto w-full max-w-7xl p-6">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold text-slate-100">Water Disruption Validation Console</h1>
        <p className="mt-1 text-sm text-slate-400">
          Shadow-mode intake, validation, canonical incidents, lifecycle, merge/split, and retractions. Notifications and production promotion remain disabled.
        </p>
      </div>
      <iframe
        src="/water-disruption/console"
        title="Water disruption validation console"
        className="min-h-[70vh] w-full rounded-lg border border-slate-800 bg-slate-950"
      />
    </main>
  )
}
