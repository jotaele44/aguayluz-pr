import { useState } from 'react'
import { useHealth, useSystemStatus, useRunExport } from '@/lib/hooks'
import { getReportUrl, postNotify } from '@/lib/api'
import { useToast } from '@/components/ui/use-toast'
import { Button } from '@/components/ui/button'
import PageHeader from '@/components/common/PageHeader'
import Panel from '@/components/common/Panel'
import { fmtDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  Bell, CheckCircle2, FileText, KeyRound, Loader2, RefreshCw, XCircle,
} from 'lucide-react'

// Channel/integration switches reported by GET /system/status. The browser cannot
// see backend env vars, so before this page every tool failed at click time with a
// toast; now each one states its requirement up front.
const CHANNELS = [
  { key: 'auth_enabled', label: 'API key auth', env: 'API_SECRET_KEY',
    hint: 'Write endpoints require a bearer token when set.' },
  { key: 'slack_configured', label: 'Slack', env: 'SLACK_WEBHOOK_URL' },
  { key: 'ntfy_configured', label: 'ntfy push', env: 'NTFY_TOPIC' },
  { key: 'email_configured', label: 'Email', env: 'NOTIFY_EMAIL_FROM / NOTIFY_EMAIL_TO' },
  { key: 'ai_enabled', label: 'AI queries', env: 'ANTHROPIC_API_KEY' },
  { key: 'sentry_dsn_set', label: 'Sentry', env: 'SENTRY_DSN' },
]

function Switch({ on, label, env, hint }) {
  const Icon = on ? CheckCircle2 : XCircle
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-slate-800 bg-slate-950/50 p-3">
      <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', on ? 'text-emerald-400' : 'text-slate-600')} />
      <div className="min-w-0">
        <div className="text-xs font-medium text-slate-200">{label}</div>
        <div className="mt-0.5 truncate font-mono text-[10px] text-slate-500" title={env}>{env}</div>
        {hint && <div className="mt-1 text-[10px] text-slate-500">{hint}</div>}
      </div>
      <span className={cn('ml-auto shrink-0 text-[10px] uppercase tracking-wide',
        on ? 'text-emerald-400' : 'text-slate-600')}>
        {on ? 'on' : 'unset'}
      </span>
    </div>
  )
}

function ArtifactRow({ name, entry }) {
  return (
    <div className="flex items-center gap-3 border-b border-slate-800/70 py-2 last:border-0">
      <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full',
        entry?.present ? 'bg-emerald-400' : 'bg-slate-700')} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs text-slate-300">{name}</div>
        <div className="truncate font-mono text-[10px] text-slate-600">{entry?.path}</div>
      </div>
      <div className="shrink-0 text-right">
        {entry?.present ? (
          <>
            <div className="font-mono text-[10px] text-slate-400">{fmtDate(entry.modified_at)}</div>
            <div className="text-[10px] text-slate-600">{Math.round((entry.bytes ?? 0) / 1024).toLocaleString()} KB</div>
          </>
        ) : (
          <span className="text-[10px] text-slate-600">not generated</span>
        )}
      </div>
    </div>
  )
}

const ARTIFACT_LABELS = {
  base44_export: 'Base44 export',
  review_queue: 'Review queue',
  integration_report: 'Integration report',
  source_manifest: 'Source manifest',
  alert_events_geojson: 'Alert map layer',
  federation_manifest: 'Federation export manifest',
}
const CORPUS_LABELS = {
  utility_assets: 'Utility assets',
  service_events: 'Service events',
  alert_events: 'Alert events',
  readings_reservoir: 'Readings — reservoir',
  readings_groundwater: 'Readings — groundwater',
  readings_coastal: 'Readings — coastal',
}

export default function SystemPage() {
  const { data: status, isLoading } = useSystemStatus()
  const { data: health, isError: healthError } = useHealth()
  const { mutate: runExport, isPending: exporting } = useRunExport()
  const [notifying, setNotifying] = useState(false)
  const { toast } = useToast()

  const up = health?.status === 'ok' && !healthError
  const notifyReady = Boolean(
    status?.slack_configured || status?.ntfy_configured || status?.email_configured,
  )
  // /admin/run-export is key-gated when API_SECRET_KEY is set, and this dashboard
  // holds no token — so the call would 401. State that up front rather than letting
  // the operator click into a failure.
  const exportBlockedByAuth = Boolean(status?.auth_enabled)
  const exportReady = up && !exportBlockedByAuth

  const handleNotify = async () => {
    setNotifying(true)
    const c = health?.counts ?? {}
    const result = await postNotify({
      title: 'AguaYLuz-PR Status Alert',
      message: `AguaYLuz-PR: ${c.alerts_active ?? 0} active alert(s), `
        + `${c.alerts_critical ?? 0} critical. ${c.assets ?? 0} assets tracked.`,
    })
    setNotifying(false)
    toast(result?.channels_active
      ? { title: 'Alert dispatched', description: `Sent to ${result.channels_active} channel(s)` }
      : { variant: 'destructive', title: 'Dispatch failed', description: result?.error || 'No channel accepted the message.' })
  }

  return (
    <div className="max-w-[1100px] space-y-6 p-6">
      <PageHeader
        title="System & Tools"
        subtitle="Backend configuration, artifact freshness, and the operator actions that depend on them"
      />

      <Panel title="Operator tools">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-[220px]">
            <Button
              size="sm"
              variant="outline"
              disabled={exporting || !exportReady}
              onClick={() => runExport(undefined, {
                onSuccess: () => toast({ title: 'Export complete', description: 'outputs/ and exports/federation regenerated' }),
                onError: (e) => toast({ variant: 'destructive', title: 'Export failed', description: String(e?.message ?? e) }),
              })}
              className="h-8 border-slate-700 bg-slate-950 text-xs text-slate-300 hover:text-slate-100"
            >
              {exporting
                ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
              {exporting ? 'Exporting…' : 'Run federation export'}
            </Button>
            <p className="mt-1.5 text-[10px] text-slate-500">
              {!up
                ? 'Unavailable — the backend is unreachable.'
                : exportBlockedByAuth
                  ? 'Unavailable — API_SECRET_KEY is set and this dashboard sends no bearer token. Run scripts/federation_export.py directly.'
                  : 'Regenerates outputs/ and exports/federation from the current corpus.'}
            </p>
          </div>

          <div className="min-w-[220px]">
            <Button
              size="sm"
              variant="outline"
              disabled={notifying || !notifyReady}
              onClick={handleNotify}
              className="h-8 border-slate-700 bg-slate-950 text-xs text-slate-300 hover:text-slate-100"
            >
              {notifying
                ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                : <Bell className="mr-1.5 h-3.5 w-3.5" />}
              {notifying ? 'Sending…' : 'Send status alert'}
            </Button>
            <p className="mt-1.5 text-[10px] text-slate-500">
              {notifyReady
                ? 'Pushes the current alert counts to every configured channel.'
                : 'Unavailable — set SLACK_WEBHOOK_URL, NTFY_TOPIC, or SMTP email vars.'}
            </p>
          </div>

          <div className="min-w-[220px]">
            <a
              href={getReportUrl()}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-700 bg-slate-950 px-3 text-xs text-slate-300 transition hover:text-slate-100"
            >
              <FileText className="h-3.5 w-3.5" /> Open status report
            </a>
            <p className="mt-1.5 text-[10px] text-slate-500">
              Printable HTML rollup — sectors, top municipios, recent events.
            </p>
          </div>
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel title="Backend configuration">
          <div className="mb-3 flex items-center gap-2 text-xs">
            <KeyRound className="h-3.5 w-3.5 text-slate-500" />
            <span className={up ? 'text-emerald-300' : 'text-red-300'}>
              Backend {up ? 'online' : 'unreachable'}
            </span>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {CHANNELS.map((c) => (
              <Switch key={c.key} on={Boolean(status?.[c.key])} label={c.label} env={c.env} hint={c.hint} />
            ))}
          </div>
        </Panel>

        <div className="space-y-6">
          <Panel title="Canonical outputs">
            {isLoading || !status
              ? <p className="text-xs text-slate-500">Loading…</p>
              : Object.entries(ARTIFACT_LABELS).map(([key, label]) => (
                  <ArtifactRow key={key} name={label} entry={status.artifacts?.[key]} />
                ))}
          </Panel>

          <Panel title="Source corpora">
            {isLoading || !status
              ? <p className="text-xs text-slate-500">Loading…</p>
              : Object.entries(CORPUS_LABELS).map(([key, label]) => (
                  <ArtifactRow key={key} name={label} entry={status.corpora?.[key]} />
                ))}
          </Panel>
        </div>
      </div>
    </div>
  )
}
