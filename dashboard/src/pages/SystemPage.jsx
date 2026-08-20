import { useMemo, useState } from 'react'
import { AlertTriangle, Bell, CheckCircle2, FileText, KeyRound, Loader2, RefreshCw, XCircle } from 'lucide-react'

import PageHeader from '@/components/common/PageHeader'
import Panel from '@/components/common/Panel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useToast } from '@/components/ui/use-toast'
import { getApiKey, getReportUrl, postNotify, setApiKey } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { useHealth, useRunExport, useSystemStatus } from '@/lib/hooks'
import { cn } from '@/lib/utils'

const CHANNELS = [
  { key: 'auth_enabled', label: 'API key auth', env: 'API_SECRET_KEY', hint: 'Write endpoints require a bearer token when set.' },
  { key: 'slack_configured', label: 'Slack', env: 'SLACK_WEBHOOK_URL' },
  { key: 'ntfy_configured', label: 'ntfy push', env: 'NTFY_TOPIC' },
  { key: 'email_configured', label: 'Email', env: 'NOTIFY_EMAIL_FROM / NOTIFY_EMAIL_TO' },
  { key: 'ai_enabled', label: 'AI queries', env: 'ANTHROPIC_API_KEY' },
  { key: 'sentry_dsn_set', label: 'Sentry', env: 'SENTRY_DSN' },
]

const ARTIFACT_LABELS = {
  hub_export: 'Hub export',
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

function PresenceCard({ state, label, env, hint }) {
  const presentation = {
    present: { Icon: CheckCircle2, text: 'present', color: 'text-emerald-400' },
    absent: { Icon: XCircle, text: 'absent', color: 'text-slate-600' },
    loading: { Icon: Loader2, text: 'checking', color: 'text-sky-400' },
    unavailable: { Icon: AlertTriangle, text: 'unavailable', color: 'text-amber-400' },
  }[state]
  const { Icon } = presentation
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-slate-800 bg-slate-950/50 p-3">
      <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', presentation.color, state === 'loading' && 'animate-spin')} />
      <div className="min-w-0">
        <div className="text-xs font-medium text-slate-200">{label}</div>
        <div className="mt-0.5 truncate font-mono text-[10px] text-slate-500" title={env}>{env}</div>
        {hint && <div className="mt-1 text-[10px] text-slate-500">{hint}</div>}
      </div>
      <span className={cn('ml-auto shrink-0 text-[10px] uppercase tracking-wide', presentation.color)}>
        {presentation.text}
      </span>
    </div>
  )
}

function ArtifactRow({ name, entry }) {
  return (
    <div className="flex items-center gap-3 border-b border-slate-800/70 py-2 last:border-0">
      <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', entry?.present ? 'bg-emerald-400' : 'bg-slate-700')} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs text-slate-300">{name}</div>
        <div className="text-[10px] text-slate-600">
          {entry?.present ? 'Generated artifact' : 'No successful generation recorded'}
        </div>
      </div>
      <div className="shrink-0 text-right">
        {entry?.present ? (
          <>
            <div className="font-mono text-[10px] text-slate-400">{fmtDate(entry.modified_at)}</div>
            <div className="text-[10px] text-slate-600">{Math.round((entry.bytes ?? 0) / 1024).toLocaleString()} KB</div>
          </>
        ) : <span className="text-[10px] text-slate-600">not generated</span>}
      </div>
    </div>
  )
}

export default function SystemPage() {
  const { data: status, isLoading, isFetching, refetch: refreshStatus } = useSystemStatus()
  const { data: health, isError: healthError } = useHealth()
  const {
    mutate: runExport,
    isPending: exporting,
    isSuccess: exportSucceeded,
    isError: exportFailed,
    error: exportError,
    reset: resetExport,
  } = useRunExport()
  const [notifying, setNotifying] = useState(false)
  const [notification, setNotification] = useState({ title: 'AguaYLuz-PR operator notice', message: '' })
  const [notificationResult, setNotificationResult] = useState(null)
  const [apiKey, setApiKeyState] = useState(getApiKey)
  const [keyDraft, setKeyDraft] = useState('')
  const { toast } = useToast()

  const up = health?.status === 'ok' && !healthError
  const authNeedsKey = Boolean(status?.auth_enabled) && !apiKey
  const exportReady = up && !authNeedsKey
  const configuredChannels = useMemo(() => [
    status?.slack_configured && 'Slack',
    status?.ntfy_configured && 'ntfy',
    status?.email_configured && 'email',
  ].filter(Boolean), [status])
  const notifyReady = configuredChannels.length > 0 && !authNeedsKey

  const handleNotify = async (event) => {
    event.preventDefault()
    setNotifying(true)
    setNotificationResult(null)
    const result = await postNotify({
      title: notification.title.trim(),
      message: notification.message.trim(),
    })
    setNotifying(false)
    const successes = Array.isArray(result?.succeeded_channels) ? result.succeeded_channels : []
    const failures = Array.isArray(result?.failed_channels) ? result.failed_channels : []
    const failureText = failures.map((failure) => (
      typeof failure === 'string'
        ? failure
        : `${failure.channel}: ${failure.error}`
    )).join('; ')
    const succeeded = successes.length > 0 && failures.length === 0
    const partial = successes.length > 0 && failures.length > 0
    const nextResult = {
      kind: succeeded ? 'success' : partial ? 'warning' : 'error',
      message: succeeded
        ? `Notification sent to ${successes.join(', ')}.`
        : partial
          ? `Notification sent to ${successes.join(', ')}. Failed: ${failureText}.`
          : failures.length
            ? `Notification delivery failed: ${failureText}.`
            : result?.error || 'No channel confirmed notification delivery.',
    }
    setNotificationResult(nextResult)
    toast(nextResult.kind === 'success'
      ? { title: 'Notification sent', description: nextResult.message }
      : { variant: 'destructive', title: partial ? 'Notification partially sent' : 'Notification failed', description: nextResult.message })
  }

  return (
    <div className="max-w-[1100px] space-y-6 p-6">
      <PageHeader
        title="System & Tools"
        subtitle="Run exports, compose notifications, and inspect credential and artifact presence"
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel title="Federation export">
          <div className="space-y-4">
            <p className="text-xs text-slate-400">
              Regenerate canonical federation outputs, then review their latest successful
              write times below. Backend diagnostics are not displayed.
            </p>
            <Button
              size="sm"
              variant="outline"
              disabled={exporting || !exportReady}
              onClick={() => {
                resetExport()
                runExport(undefined, {
                  onSuccess: () => toast({ title: 'Export complete', description: 'Canonical outputs were regenerated.' }),
                  onError: (error) => toast({ variant: 'destructive', title: 'Export failed', description: String(error?.message ?? error) }),
                })
              }}
            >
              {exporting ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              {exporting ? 'Exporting…' : 'Run federation export'}
            </Button>
            <p className="text-[10px] text-slate-500">
              {!up
                ? 'Unavailable — the backend is unreachable.'
                : authNeedsKey
                  ? 'Unavailable — enter the API key for this tab below.'
                  : 'Regenerates supported outputs from the current corpus.'}
            </p>
            <div aria-live="polite">
              {exporting && <p role="status" className="text-xs text-sky-300">Export is running. This may take up to two minutes.</p>}
              {exportSucceeded && <p role="status" className="text-xs text-emerald-300">Export completed successfully. Artifact status is refreshing.</p>}
              {exportFailed && <p role="alert" className="text-xs text-red-300">{String(exportError?.message ?? 'Export failed.')}</p>}
            </div>
            <div>
              <a
                href={getReportUrl()}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-700 bg-slate-950 px-3 text-xs text-slate-300 transition hover:text-slate-100"
              >
                <FileText className="h-3.5 w-3.5" /> Open status report
              </a>
              <p className="mt-1.5 text-[10px] text-slate-500">Printable HTML rollup of current system data.</p>
            </div>
          </div>
        </Panel>

        <Panel title="Compose notification">
          <form className="space-y-3" onSubmit={handleNotify}>
            <div>
              <label htmlFor="notification-title" className="mb-1 block text-xs text-slate-300">Title</label>
              <Input
                id="notification-title"
                value={notification.title}
                maxLength={160}
                onChange={(event) => setNotification((value) => ({ ...value, title: event.target.value }))}
                className="border-slate-700 bg-slate-950 text-slate-200"
              />
            </div>
            <div>
              <label htmlFor="notification-message" className="mb-1 block text-xs text-slate-300">Message</label>
              <textarea
                id="notification-message"
                value={notification.message}
                maxLength={2000}
                rows={5}
                onChange={(event) => setNotification((value) => ({ ...value, message: event.target.value }))}
                placeholder="Write an operator-facing notification"
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sky-500"
              />
            </div>
            <p className="text-[10px] text-slate-500">
              {notifyReady
                ? `Will send to all configured channels: ${configuredChannels.join(', ')}.`
                : authNeedsKey
                  ? 'Sending is unavailable until an API key is set for this tab.'
                  : isLoading
                    ? 'Checking notification channel readiness…'
                    : !status
                      ? 'Notification channel readiness is unavailable.'
                      : 'No notification channels are configured on the backend.'}
            </p>
            <Button
              type="submit"
              size="sm"
              variant="outline"
              disabled={notifying || !notifyReady || !notification.title.trim() || !notification.message.trim()}
            >
              {notifying ? <Loader2 className="animate-spin" /> : <Bell />}
              {notifying ? 'Sending…' : 'Send notification'}
            </Button>
            {notificationResult && (
              <p
                role={notificationResult.kind === 'error' ? 'alert' : 'status'}
                className={cn('text-xs', notificationResult.kind === 'success'
                  ? 'text-emerald-300'
                  : notificationResult.kind === 'warning' ? 'text-amber-300' : 'text-red-300')}
              >
                {notificationResult.message}
              </p>
            )}
          </form>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel title="System credential presence">
          <div className="mb-3 flex items-center gap-2 text-xs">
            <KeyRound className="h-3.5 w-3.5 text-slate-500" />
            <span className={up ? 'text-emerald-300' : 'text-red-300'}>Backend {up ? 'online' : 'unreachable'}</span>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {CHANNELS.map(({ key, ...channel }) => {
              const state = isLoading
                ? 'loading'
                : !status
                  ? 'unavailable'
                  : status[key] ? 'present' : 'absent'
              return <PresenceCard key={key} state={state} {...channel} />
            })}
          </div>
          {!isLoading && !status && (
            <p role="alert" className="mt-3 text-xs text-red-300">
              Credential presence is unavailable because system status could not be loaded.
            </p>
          )}
        </Panel>

        <Panel title="API key for this tab">
          <p className="mb-3 text-[11px] text-slate-400">
            The dashboard can only store an operator-provided API key in session storage.
            It can report whether backend credentials are present, but it never reads or
            displays their values.
          </p>
          {isLoading ? (
            <p role="status" className="text-xs text-sky-300">Checking backend authentication status…</p>
          ) : !status ? (
            <p role="alert" className="text-xs text-amber-300">
              Backend authentication status is unavailable. No assumption is made about whether a key is required.
            </p>
          ) : status.auth_enabled ? (
            <form
              className="flex flex-wrap items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                setApiKey(keyDraft)
                setApiKeyState(keyDraft)
                setKeyDraft('')
                toast({ title: 'API key set', description: 'Write actions are enabled for this tab.' })
              }}
            >
              <Input
                type="password"
                value={keyDraft}
                onChange={(event) => setKeyDraft(event.target.value)}
                placeholder={apiKey ? 'Key set — enter a replacement' : 'Enter API key'}
                aria-label="API key"
                autoComplete="off"
                className="h-8 min-w-[240px] flex-1 border-slate-700 bg-slate-950 font-mono text-xs text-slate-200"
              />
              <Button type="submit" size="sm" variant="outline" disabled={!keyDraft}>
                {apiKey ? 'Replace key' : 'Set key'}
              </Button>
              {apiKey && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setApiKey('')
                    setApiKeyState('')
                    toast({ title: 'API key cleared' })
                  }}
                >
                  Clear
                </Button>
              )}
              <span role="status" className={cn('text-[10px] uppercase tracking-wide', apiKey ? 'text-emerald-400' : 'text-amber-400')}>
                {apiKey ? 'key present' : 'key absent'}
              </span>
            </form>
          ) : (
            <p role="status" className="text-xs text-emerald-300">
              Backend write authentication is not enabled; no API key is required.
            </p>
          )}
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel title="Export artifact history">
          <div className="mb-3 flex items-center justify-between gap-3">
            <p className="text-[10px] text-slate-500">
              Latest successful write time reported for each supported artifact.
            </p>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={isFetching}
              onClick={() => refreshStatus()}
              aria-label="Refresh export status"
            >
              <RefreshCw className={cn(isFetching && 'animate-spin')} /> Refresh
            </Button>
          </div>
          {isLoading
            ? <p role="status" className="text-xs text-slate-500">Loading export status…</p>
            : !status
              ? <p role="alert" className="text-xs text-red-300">Export status is unavailable.</p>
              : Object.entries(ARTIFACT_LABELS).map(([key, label]) => (
                  <ArtifactRow key={key} name={label} entry={status.artifacts?.[key]} />
                ))}
        </Panel>

        <Panel title="Source corpora">
          {isLoading
            ? <p role="status" className="text-xs text-slate-500">Loading source status…</p>
            : !status
              ? <p role="alert" className="text-xs text-red-300">Source status is unavailable.</p>
              : Object.entries(CORPUS_LABELS).map(([key, label]) => (
                  <ArtifactRow key={key} name={label} entry={status.corpora?.[key]} />
                ))}
        </Panel>
      </div>
    </div>
  )
}
